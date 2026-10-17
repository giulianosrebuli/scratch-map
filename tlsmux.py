"""HTTP e HTTPS na mesma porta, na frente do gunicorn.

O PWA só instala no Android com HTTPS, e o certificado válido (do Tailscale)
só vale para o nome da máquina na tailnet (<máquina>.<tailnet>.ts.net). Pelo
IP (rede de casa ou tailnet) não há certificado possível: aí o acesso continua
em HTTP. Este processo escuta a porta pública e olha o primeiro byte de cada
conexão: 0x16 é o início de um handshake TLS (decifra com o certificado e
repassa), qualquer outro é HTTP puro (repassa direto). O gunicorn fica só em
127.0.0.1.

SIGHUP relê o certificado (deploy/renew-cert.sh, depois de renovar).

Uso: python tlsmux.py --listen 0.0.0.0:5020 --backend 127.0.0.1:5021 --cert cert.pem --key key.pem
"""
import argparse
import asyncio
import logging
import signal
import socket
import ssl

log = logging.getLogger("tlsmux")
TLS_HANDSHAKE = 0x16
CHUNK = 256 * 1024


def addr(s):
    host, _, port = s.rpartition(":")
    return host, int(port)


class Mux:
    def __init__(self, backend, cert, key):
        self.backend, self.cert, self.key = backend, cert, key
        self.ctx = None
        self.reload()

    def reload(self):
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(self.cert, self.key)
        ctx.set_alpn_protocols(["http/1.1"])
        self.ctx = ctx
        log.info("certificado carregado: %s", self.cert)

    async def peek(self, sock):
        """Primeiro byte da conexão, sem consumir (None: fechou ou demorou)."""
        loop = asyncio.get_running_loop()
        ready = loop.create_future()
        loop.add_reader(sock.fileno(), lambda: ready.done() or ready.set_result(None))
        try:
            await asyncio.wait_for(ready, 30)
            first = sock.recv(1, socket.MSG_PEEK)
        except (asyncio.TimeoutError, OSError):
            return None
        finally:
            loop.remove_reader(sock.fileno())
        return first[0] if first else None

    async def handle(self, sock):
        try:
            await self.relay(sock)
        except Exception:
            log.exception("conexão")
            sock.close()

    async def relay(self, sock):
        loop = asyncio.get_running_loop()
        first = await self.peek(sock)
        if first is None:
            sock.close()
            return
        reader = asyncio.StreamReader(limit=CHUNK)
        proto = asyncio.StreamReaderProtocol(reader)
        tls = {"ssl": self.ctx, "ssl_handshake_timeout": 30} if first == TLS_HANDSHAKE else {}
        try:
            transport, _ = await loop.connect_accepted_socket(lambda: proto, sock, **tls)
        except (OSError, ssl.SSLError, asyncio.TimeoutError) as e:
            log.debug("conexão recusada: %s", e)  # ex.: aceitou o aviso de certificado e desistiu
            sock.close()
            return
        writer = asyncio.StreamWriter(transport, proto, reader, loop)
        try:
            b_reader, b_writer = await asyncio.open_connection(*self.backend, limit=CHUNK)
        except OSError:
            writer.close()  # gunicorn reiniciando: o navegador tenta de novo
            return
        await asyncio.wait([asyncio.ensure_future(self.pipe(reader, b_writer)),
                            asyncio.ensure_future(self.pipe(b_reader, writer))],
                           return_when=asyncio.FIRST_COMPLETED)
        for w in (writer, b_writer):
            w.close()

    @staticmethod
    async def pipe(src, dst):
        try:
            while data := await src.read(CHUNK):
                dst.write(data)
                await dst.drain()
        except (OSError, ssl.SSLError, asyncio.IncompleteReadError):
            pass


async def serve(listen, mux):
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGHUP, mux.reload)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(listen)
    srv.listen(256)
    srv.setblocking(False)
    log.info("escutando %s:%s (HTTP e HTTPS) -> %s:%s", *listen, *mux.backend)
    while True:
        sock, _ = await loop.sock_accept(srv)
        sock.setblocking(False)
        asyncio.ensure_future(mux.handle(sock))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=addr, default=("0.0.0.0", 5020))
    ap.add_argument("--backend", type=addr, default=("127.0.0.1", 5021))
    ap.add_argument("--cert", required=True)
    ap.add_argument("--key", required=True)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(serve(args.listen, Mux(args.backend, args.cert, args.key)))
