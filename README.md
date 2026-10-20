# scratch-map

*A self-hosted digital scratch map.* Um mapa de raspar digital, que roda na
sua própria máquina.

Marque os lugares por onde passou, **países, estados, cidades, aeroportos e
monumentos**, cada tipo com sua cor, e eles "raspam" no mapa. Cada lugar pode
ter várias fotos, mostradas como cópias impressas, com a data na margem branca.
Tudo fica no seu servidor: mapa, visitas e fotos.

Pensado para uma casa: cada pessoa tem o seu **perfil** (visitas, fotos e
configurações próprias), **sem login**. Ele confia em quem está na rede de
casa ou na sua VPN.

Roda na porta **`:5020`**, em Docker (veja "Instalação") ou como serviço
systemd de usuário. Acesso pela rede de casa ou por VPN (ex.: Tailscale).

## Funcionalidades

- **Camadas liga/desliga**: os 5 botões do topo (Países, Estados, Cidades,
  Aeroportos, Monumentos, com a contagem de cada um; no celular só ícone e
  contagem) ligam e desligam cada destaque no mapa. A escolha fica salva no
  navegador.
- **Idioma**: português ou inglês, escolhido no primeiro cartão do assistente
  (antes de "Começar do zero") e trocável em Configurações → Aparência. Os
  textos ficam em `i18n/<idioma>.json`, com o português como chave (veja
  `i18n.py`); sem tradução, aparece o português. Países seguem o idioma
  (Alemanha / Germany); estados e cidades ficam com o nome de lá (Bayern,
  München), ou em inglês quando ele não é escrito em alfabeto latino (東京都 →
  Tokyo). A busca acha por qualquer um dos nomes (baviera, bavaria, bayern).
- **Bordas**: em Configurações → Mapa, liga/desliga a linha branca entre
  países, entre estados e em volta das cidades visitadas (esta, desligada por
  padrão).
- **Barra de menu na base** (estilo liquid glass, flutuando sobre a tela): abas
  **Mapa**, **Mural** e **Perfil** e o botão **+** (adicionar), centralizados.
  As configurações ficam dentro do Perfil (engrenagem no cabeçalho).
- **Gaveta**: o mapa ocupa a tela toda; o resto abre numa gaveta flutuante
  (mais estreita que a tela, cantos arredondados) que sobe de baixo, cobre a
  barra e trava o mapa. Tocar fora, arrastar a alça para baixo, o × ou Esc
  recolhem; o ‹ volta para a tela anterior da gaveta.
  - **Lugar com foto**: a foto mais recente (horizontal de preferência;
    vertical só se não houver) vira o topo da gaveta, de ponta a ponta, com o
    nome sobre um desfoque leve. A gaveta abre só com a altura da foto;
    arrastar para cima (pela alça ou pela foto) ou tocar na alça expande até
    85% da tela, e arrastar para baixo volta à foto e depois recolhe. Tocar na
    foto abre o lightbox.
- **Adicionar** (botão +):
  - **Cidade**: busca (nome sem acento funciona) e **bandeira azul**
    (contorno = não visitado, cheia = visitado);
  - **Lista de cidades**: várias de uma vez. País → estado (opcional) →
    cidades das maiores para as menores, com filtro por nome; tocar escolhe.
    Marcadas, uma cena só raspa tudo junto; os contornos chegam aos poucos;
  - **Aeroporto**: busca pelo nome, pela cidade ou pelo código IATA (GRU) e
    a mesma bandeira (aeroporto não marca a cidade nem o país);
  - **Monumento**: a partir de foto (veja "Monumentos");
  - **Foto**: busca qualquer lugar (país, estado, cidade, aeroporto ou
    monumento); tocar nele abre a escolha dos arquivos e, depois do envio, o
    lugar.
- **Raspagem ao marcar**: o lugar novo (cidade, estado, país) não pinta de
  uma vez: a película (o mapa de antes) é raspada em 5 s, soltando lascas.
  Os lugares novos entram um a um, do maior para o menor (país → estado →
  cidade): a gaveta sai, o mapa enquadra cada um e raspa; no fim a gaveta
  volta. "Toque para pular" termina na hora. A marcação em si é gravada
  antes, a cena só mostra.
- **Tocar no mapa** abre o lugar na gaveta, o mais específico entre as camadas
  ligadas: contorno de cidade → aeroporto → estado → país. Tocando num
  estado/país, a gaveta lista também as cidades e aeroportos perto de onde
  você tocou, já com a bandeira para marcar (é por aí que se marca aeroporto,
  estado ou país direto).
- **Perfis** (`/profiles`): cada pessoa da casa com suas visitas, fotos e
  configurações, sem senha (confia em quem está na rede, como o resto do
  app). Com um perfil só, nada muda: ele é usado direto. Com mais de um, cada
  aparelho pergunta "quem está usando?" uma vez e lembra (cookie); trocar fica
  no cabeçalho do Perfil. "Adicionar perfil" passa pelo assistente (idioma,
  nome e foto, vista inicial, lista de cidades; ou **importar um perfil**
  exportado de outra instalação), sem a parte dos dados do mapa, que são da
  casa toda. Em Configurações → Perfil: **exportar este perfil** (um .zip só
  com os dados dele) e apagar (não com o único perfil; só move a pasta para
  `data/profiles-removed/`). O que o navegador guarda (vista "onde parei",
  camadas, ordem do mural) também é por perfil.
- **Perfil** (`/profile`): no topo, nome e foto
  de perfil, editáveis ali mesmo (tocar na foto troca; a foto vira um
  quadrado de 512 px em `profile.jpg`, na pasta do perfil). Ao lado, os
  botões de trocar de perfil e de configurações. Abaixo, o álbum de bandeiras.
  Álbum: Totais no topo; países como
  círculos com a bandeira (visitados em cor, os outros bem apagados; a lista
  dos não visitados começa dobrada, com "Ver mais"). Tocar
  num país mostra os estados; num estado, as cidades; numa cidade, abre no
  mapa (`/profile#BR`, `/profile#BR/BR-SP`). Estado/cidade sem bandeira mostra a
  sigla. No fim, as listas de aeroportos e monumentos.
- **Data da visita**: na gaveta do lugar, **Quando** guarda ano e mês de cada
  visita (pode ter várias; o ano vai até o atual). O mês é opcional: para
  lugar onde morou, ou viagem de que só lembra o ano, fica só o ano (que
  também cala as sugestões das fotos daquele ano). "até…" vira **período**
  (2010 – 2018, ou com meses), que entra em todos os anos dele no Perfil e
  cala as sugestões das fotos do período. Pôr uma data num lugar não
  marcado já marca. Estado e país mostram também as datas do que tem dentro
  deles (cidades, aeroportos, monumentos), e a cidade, as dos monumentos dela.
  Fotos com data de um mês sem visita aparecem como sugestão ("+ SET 2015
  pelas fotos"): um toque grava, nada é gravado sozinho. Desmarcar o lugar
  apaga as datas dele (com aviso). A última visita (dele ou herdada) aparece
  ao lado de estado e país, embaixo do nome, já com a gaveta recolhida
  ("São Paulo · Brasil · out. 2026").
- **Marcação implícita**: cidade marca o estado e o país dela; estado marca o
  país. **Aeroporto não marca nada.** O implícito é calculado na hora, não é
  gravado: desmarcar a última cidade de um estado desmarca o estado, a menos que
  ele também tenha sido marcado explicitamente. Na tela, **visitado é
  visitado**: não importa como foi marcado. Tentar desmarcar um estado/país que
  só está marcado pelas cidades mostra um aviso (desmarque as cidades).
- **Fotos**: várias por lugar (inclusive HEIC do iPhone). A data vem do EXIF
  (`DateTimeOriginal`); sem EXIF fica "SEM DATA" e dá para editar clicando na
  data na foto ampliada. Só a data é guardada, nunca a hora. Enviar foto para um
  lugar não visitado já marca o lugar. As fotos vêm das mais recentes para as
  mais antigas.
- **Fotos sobem na hierarquia** (cidade ⊂ estado ⊂ país): a cidade mostra
  também as fotos dos monumentos e aeroportos dela; o estado e o país mostram as próprias e,
  abaixo, um grupo por cidade contida (aeroporto entra pela cidade mais
  próxima). As fotos não são copiadas: apagar ou mudar a data em qualquer tela
  muda a original. A contagem 📷 do estado/país é só a do próprio lugar; a da
  cidade inclui os monumentos.
- **Mural** (`/mural`, aba "Mural" da barra): todas as fotos, impressas e
  "jogadas" sobre uma mesa de madeira clara, num tom nude (escura no tema escuro), com
  inclinação e deslocamento fixos por foto, sem sobrepor. A grade é contínua:
  os rótulos são etiquetas de papel no meio das fotos, sem quebrar a linha.
  - **Linha do tempo**: uma etiqueta por mês (a do primeiro mês de cada ano
    em amarelo); o botão ao lado inverte entre mais novas e mais antigas
    primeiro (fica salvo no navegador); as sem data sempre no fim;
  - **Por localidade**: uma etiqueta por lugar (cidade em ordem alfabética;
    fotos de estado/país viram "Nome (estado)"/"Nome (país)"); o nome abre o
    lugar no mapa.
  Clicar numa foto amplia, com setas pelo mural todo e "Abrir <lugar>", que
  leva ao mapa.
- **Cidade com limite preenchido**: ao marcar uma cidade, o contorno do
  município é calculado uma vez (dados locais do Overture/OSM; no modo Leve,
  pedido ao Nominatim) e pintado no mapa; a costa e as divisas coincidem com as do estado e do país. A cidade
  aparece só pelo contorno preenchido, sem pin; de longe, cidade pequena fica
  com poucos pixels. Cidade sem área no Overture aparece como pin (bolinha).
  Veja "Limites das cidades" abaixo.
- **Monumentos** (no código e na API, `landmark`; pontos turísticos, restaurantes, o que quiser): só nascem de
  uma foto. Em **+ → Monumento**:
  - a posição vem do **GPS da foto** (EXIF); sem GPS (prints, fotos do
    WhatsApp, iPhone que tirou a localização ao enviar), toque no mapa. O
    marcador é arrastável. Nesse formulário a gaveta fica mais baixa e não
    trava o mapa;
  - o nome é **sugerido pelo OpenStreetMap** a partir das coordenadas, e você
    pode trocar;
  - **não marca nada sozinho**: o formulário oferece "também marcar como
    visitado" a cidade mais próxima, o estado e o país, tudo desmarcado. A
    cidade é a que tem o contorno (de uma cidade marcada) contendo o ponto, ou
    a mais próxima, com preferência para as grandes;
  - no mapa é um **alfinete** de longe e, a partir do zoom 8, a **miniatura da
    foto impressa**. A capa é a foto mais antiga;
  - dá para renomear, mover e adicionar fotos. Apagar a última foto apaga o
    monumento (as fotos vão para o trash). Rascunho abandonado (fechou a página
    no meio do formulário) é apagado no próximo início do serviço, depois de
    um dia.
- **Configurações** (`/settings`, engrenagem no cabeçalho do Perfil):
  - **Aparência**: idioma; tema claro, escuro ou automático (segue o sistema;
    no escuro, as fotos impressas continuam papel branco); cores do mapa
    (água, terra, país, estado, cidade, aeroporto, monumento), com prévia ao
    vivo e "Restaurar cores padrão";
  - **Mapa**: formato (plano ou globo); bordas; vista inicial (cidades
    visitadas num país, todas as visitadas, onde parou, por aparelho, ou uma
    posição fixa, escolhida arrastando um mapa pequeno ali mesmo). Ao abrir
    o app (uma vez por sessão), o mapa começa de longe e desce até a vista
    inicial em ~2,4 s; voltando de outra tela vai direto. **Pular animações**
    (por perfil) tira essa descida e a raspagem ao marcar; "reduzir
    movimento" no sistema também;
  - **Dados e privacidade**: um
    liga/desliga para cada pedido que sai da máquina (sugestão de nome do
    monumento e contorno de cidade, no Nominatim; bandeiras de estado, no
    Wikidata/Commons), dizendo o que sai e para quem. Desligado, o pedido não
    acontece;
  - **Perfil**: exportar este perfil; apagar;
  - **Backup do servidor**: baixar um .zip com todos os perfis; restaurar.
  - **Sobre**, no fim: versão e data de publicação (`version.py`), link do
    código e, em "Dados do mapa", o modo (Leve/Completo), a versão do
    Overture, a data da montagem e as fontes com as licenças.
  Fica tudo na tabela `settings` (vale em todos os aparelhos) e entra no
  `<head>` de cada página (`templates/_head.html`).
- **Globo/plano**: escolhido na configuração (Mapa → Formato). No globo o
  fundo é espaço escuro, com halo de atmosfera.

### Cores

| Item       | Cor                     |
|------------|-------------------------|
| Água       | `#86b9dc` azul          |
| Terra      | `#8db37c` verde         |
| País       | `#f2b143` âmbar         |
| Estado     | `#e5705b` coral         |
| Cidade     | `#6a4bc0` roxo (contorno do município; pin só sem contorno) |
| Aeroporto  | `#1f3a68` azul-marinho (ícone de avião) |
| Monumento  | `#0d7f73` verde-petróleo (alfinete; de perto, a foto) |
| Bandeira "estive aqui" | `#2563eb` azul |

As cores ficam em variáveis no topo de `static/app.css` (o mapa lê as mesmas
variáveis).

## Stack

- **Backend**: Python 3.12 + Flask + gunicorn, SQLite, Pillow (+ pillow-heif),
  shapely e DuckDB (contorno de cidade).
- **Frontend**: HTML + JS puro, sem build. Mapa com [MapLibre GL JS](https://maplibre.org/)
  v5 e [PMTiles](https://github.com/protomaps/PMTiles), servidos localmente de
  `static/vendor/`. Não usa tiles externos: países e estados vêm de um arquivo
  de tiles vetoriais local, então funciona sem internet.

## Estrutura

```
scratch-map/
├── app.py                    # backend Flask (API + páginas)
├── boundaries.py             # contorno das cidades (sob demanda) e nome de monumento
├── flags.py                  # bandeiras de estado (Wikidata, em segundo plano)
├── geoshapes.py              # recorte pelo litoral e busca da área de cidade (Overture)
├── installer.py              # primeira execução: assistente e montagem dos dados do mapa
├── profiles.py               # perfis da casa: uma pasta de dados por pessoa
├── tlsmux.py                 # HTTP e HTTPS na mesma porta, na frente do gunicorn (opcional)
├── i18n.py, i18n/en.json     # tradução (o texto em português é a chave)
├── Dockerfile, docker-compose.yml
├── setup.sh                  # prepara uma instância do zero (venv + geodata)
├── requirements.txt
├── scripts/build_geodata.py  # baixa e processa os dados geográficos
├── scripts/migrate_ids.py    # converte visitas para ids novos de estado/país
├── templates/index.html      # mapa
├── templates/mural.html      # mural de fotos
├── templates/profile.html    # perfil (nome, foto) + álbum de bandeiras
├── templates/profiles.html   # "quem está usando?" (escolher e adicionar perfil)
├── templates/settings.html   # configurações
├── templates/setup.html      # assistente de primeira execução
├── templates/_navbar.html    # barra de menu na base, comum às telas
├── templates/_head.html      # <head> comum: CSS, cores escolhidas, ícone e PWA
├── templates/offline.html    # "sem conexão" (guardada pelo service worker)
├── templates/api-docs.html   # documentação da API (/api/docs)
├── docs/openapi.yaml         # especificação da API (OpenAPI 3.1)
├── static/
│   ├── common.js             # helpers, foto impressa e lightbox (mapa + mural)
│   ├── app.js / app.css      # mapa (o CSS serve a todas as páginas)
│   ├── mural.js              # mural
│   ├── stats.js              # álbum de bandeiras (no perfil)
│   ├── profile.js            # nome e foto do perfil
│   ├── config.js             # configurações
│   ├── setup.js              # assistente de primeira execução (e de perfil novo)
│   ├── backdrop.js           # fundo do assistente e da escolha de perfil (mundo girando)
│   ├── citypicker.js         # lista de cidades (marcar várias; assistente e +)
│   ├── sw.js                 # service worker (servido em /sw.js): só a página "sem conexão"
│   ├── icons/                # ícone do app (globo): PWA, iPhone e favicon
│   └── vendor/               # MapLibre + PMTiles; Redoc (página da API); flags/ = bandeiras (flag-icons, MIT);
│                             # world-lite.geojson = mundo do fundo do assistente (Natural Earth)
├── geodata/                  # gerado, não versionado (veja "Dados geográficos")
│   ├── world.pmtiles         # tiles de países e estados (~700 MB)
│   ├── geo.db                # países, estados, cidades, aeroportos
│   ├── localities/           # áreas de cidade do Overture (parquet em blocos de 10°; só no modo Completo)
│   ├── localities_large.parquet  # as com mais de 3° (ex.: Vitória + ilha da Trindade; só no Completo)
│   ├── land.parquet          # litoral do OSM
│   ├── geodata.json          # versão do Overture e modo (leve/completo) da montagem
│   ├── build-status.json, build.log  # andamento da montagem pelo assistente
│   └── raw/ work/            # downloads e intermediários do build (dá para apagar)
├── data/                     # SEUS DADOS (não versionado — faça backup)
│   ├── setup.json            # o que o assistente decidiu (concluído, modo): da casa toda
│   ├── backup.json           # quando foi baixado o último backup do servidor
│   ├── backups/              # cópias automáticas "antes de restaurar" (3 últimas)
│   ├── profiles/<id>/        # um por perfil (profiles.py):
│   │   ├── scratch.db        #   visitas, monumentos, metadados das fotos, limites das cidades, configurações
│   │   ├── flags/            #   bandeiras de estado baixadas do Wikidata (<ID>.webp)
│   │   ├── profile.jpg       #   foto de perfil
│   │   └── photos/{orig,display,thumb,trash}/
│   └── profiles-removed/     # perfis apagados (<id>-<data>; dá para trazer de volta à mão)
└── deploy/
    ├── scratch-map.service   # unit do systemd (usuário): o gunicorn
    ├── scratch-map-tls.service  # tlsmux na porta pública (HTTP e HTTPS; opcional)
    └── renew-cert.sh, scratch-map-cert.{service,timer}  # renova o certificado do Tailscale
```

## Bandeiras

- **Países**: prontas, do [flag-icons](https://github.com/lipis/flag-icons)
  (MIT), versão quadrada, em `static/vendor/flags/` (250 países e 10
  subdivisões que o pacote traz, como Inglaterra, Escócia e Catalunha).
- **Estados**: quando um país passa a ser visitado (e, na subida do serviço,
  para os já visitados), `flags.py` pede ao Wikidata, em segundo plano, as
  bandeiras dos estados dele, ligando pelo código ISO 3166-2 (o mesmo id do
  app, ex. `BR-SP`), e guarda uma miniatura de 160 px em
  `flags/<ID>.webp`, na pasta do perfil (~5 KB cada; os 27 do Brasil somam 140 KB). Cada país
  é buscado uma vez (tabela `state_flags_fetched`); sem rede, tenta de novo
  na próxima marcação ou subida. Quando o Wikidata limita as requisições
  (429), espera e tenta de novo.
- **Exceção ao "nada sai da máquina"**: saem o código do país (consulta ao
  Wikidata) e os nomes dos arquivos das bandeiras (download do Commons).
  Visitas e fotos, não. Dá para desligar na configuração (Dados e
  privacidade); as já baixadas continuam.
- Estado sem bandeira no Wikidata (ou país que não usa) e cidades: sigla.
- Para buscar de novo (pegar as que faltaram ou foram cadastradas depois):
  Configurações → Dados e privacidade → "Buscar bandeiras de novo".

## Dados geográficos

País, estado e cidade vêm **da mesma fonte** e são **recortados pelo mesmo
litoral**, então as três camadas se sobrepõem perfeitamente: as divisas são as
mesmas linhas do OpenStreetMap e a costa é a mesma em todas.

| Fonte | Uso | Licença |
|---|---|---|
| [Overture Maps](https://overturemaps.org/), tema *divisions* (a release mais nova na hora da montagem) | países, estados e áreas de cidade (dados do OpenStreetMap) | ODbL |
| [OSM land polygons](https://osmdata.openstreetmap.de/data/land-polygons.html) | litoral, para recortar tudo acima | ODbL |
| [GeoNames](https://www.geonames.org/) `cities1000` | ~171 mil cidades com ≥1000 hab. (busca e ponto) | CC-BY 4.0 |
| [OurAirports](https://ourairports.com/data/) | ~5,3 mil aeroportos com código IATA (grandes/médios, ou pequenos com voo regular) | domínio público |

Atribuição obrigatória ("Overture Maps · © OpenStreetMap contributors"):
fica em Configurações → Sobre → Dados do mapa, junto com as outras fontes. Os arquivos gerados a partir deles (`world.pmtiles`,
`localities/`, `land.parquet`) também ficam sob ODbL.

**Como é montado** (`scripts/build_geodata.py`, etapas retomáveis):

1. **download** (~6 GB): do Overture, a versão *territorial* (sem recorte) de
   países, dependências e estados, os nomes e as áreas de cidade; o litoral do
   OSM; GeoNames e OurAirports. O Overture também tem uma versão já recortada,
   mas cada nível vem recortado com uma precisão diferente (perto do Rio, o
   litoral do estado tem 138 pontos e o dos municípios ~14 mil), por isso o
   recorte é nosso.
2. **clip** (~30 min): cada país/estado vira só a parte em terra. Feições
   grandes são processadas em quadrados de 5° para caber na memória.
3. **tiles** (~45 min): cada feição é separada em polígonos, simplificada a
   ~1 m (menos que um pixel no zoom 12) e vai para o
   [tippecanoe](https://github.com/felt/tippecanoe), que gera o
   `world.pmtiles` (zoom 0–12; o mapa aproxima até 14 esticando o 12). Ele
   simplifica as divisas compartilhadas do mesmo jeito dos dois lados.
4. **db**: `geo.db` com países, estados (com bbox, para o mapa enquadrar),
   cidades e aeroportos. Cidade → estado é resolvida **por geometria** (ponto
   dentro do estado), com fallback para o mais próximo até 0,5° (ponto do
   GeoNames que cai no mar).

Num notebook de 8 GB levou ~1h30. Requer `tippecanoe` no PATH (ou na variável
`TIPPECANOE`); compile com `make` a partir do repositório dele (a imagem Docker
já traz).

Opções: `--mode leve` pula as áreas de cidade; `--release` fixa a versão do
Overture (sem ela, a mais nova do bucket público; a usada fica em
`geodata/geodata.json`, com o modo); `--cleanup` apaga `raw/` e `work/` no fim;
`--status` grava o andamento em JSON e `--simulate PASTA` imita as etapas
copiando arquivos prontos (os dois usados pelo assistente).

**O navegador não baixa o arquivo inteiro**: o PMTiles é lido por trechos
(cabeçalho HTTP `Range`), só os tiles da área e do zoom na tela. Abrir o mapa
baixa ~0,4–1,3 MB.

**ids**: país = ISO 3166-1 alfa-2 (`BR`; dependências como `PR`, `GL` têm o
próprio); estado = ISO 3166-2 (`BR-RJ`) ou, quando não há (376 casos, ex.
municípios de Porto Rico), o id da divisão no Overture; cidade = geonameid;
aeroporto = código IATA. O "estado" é o primeiro nível abaixo do país no OSM e
varia por país: no Brasil e nos EUA são os estados; na França, as regiões.

Para refazer uma etapa: `venv/bin/python scripts/build_geodata.py --redo db`.
A release do Overture usada fica em `geodata/work/release.txt` enquanto os
intermediários existirem; para trocar, apague `geodata/work/` e os `.parquet`
e rode de novo (com `--release`, ou sem ele para a mais nova). A pasta dos dados pode ser outra com
`SCRATCH_GEODATA=/caminho`.

Se os ids de estado/país mudarem num rebuild, as visitas antigas param de
aparecer até rodar `scripts/migrate_ids.py`, que acha o novo id pelo polígono
antigo (maior sobreposição) e mostra o de-para antes de aplicar.

## Limites das cidades

O GeoNames só tem o ponto central de cada cidade. O contorno vem das áreas de
cidade do Overture (`geoshapes.py`), calculado **uma vez por cidade, ao
marcar** (~1 s), e guardado no `scratch.db` do perfil (tabela `city_shapes`):

1. Áreas (`locality`, `localadmin`, `county`) que contêm o ponto.
2. Entre as de **nome igual** (ou, se não houver, **parecido**: "New York" ⊂
   "New York City"), a maior: o município inteiro, não só a mancha urbana ou o
   distrito. Sem nome parecido, a menor que contém o ponto, com menos de 3° (em
   Tóquio, o distrito). Áreas com mais de 3° só valem com o nome igual (ex.:
   Vitória, que inclui a ilha da Trindade).
3. Recorte pelo litoral (o mesmo dos tiles) e simplificação a ~1 m.

Área com o mesmo contorno do estado da cidade é descartada (erro do dado: no
Overture, o "Plano Piloto" é o Distrito Federal inteiro). Nesse caso, e só
nele, o contorno é pedido **uma vez ao Nominatim** (busca por nome; senão
reverso no ponto, zoom 10) e passa pelo mesmo recorte do litoral. Fica marcado
em `city_shapes.method` como `nominatim:search` / `nominatim:reverse`.

> **Ressalva (ajuste futuro):** é uma das exceções ao "nada sai da máquina" e à
> fonte única. Hoje só afeta Brasília. As divisas desse contorno com as
> cidades vizinhas podem não coincidir exatamente com as do Overture. Opções
> para resolver: reportar/corrigir o dado no OSM/Overture (some sozinho no
> próximo release) ou montar localmente as regiões administrativas do OSM.

`ok` / `none` (sem área de cidade: fica só o pin) / `error` (tenta de novo).
Ao subir o serviço, uma thread calcula as cidades marcadas que ainda não têm
contorno. Para recalcular uma cidade, apague a linha dela em `city_shapes` e
reinicie.

**O que sai da máquina**: para o mapa, nada. Para o Nominatim
(`nominatim.openstreetmap.org`) vão só: as coordenadas de um monumento novo
(`/reverse`, zoom 18, para sugerir o nome) e, na exceção acima (ou para toda
cidade marcada, no modo Leve), nome, país e coordenadas da cidade. Fotos e a lista de visitas nunca
saem. Respeitamos a política de uso (no máximo 1 req/s, User-Agent próprio).

## Instalação

### Com Docker (recomendado para uma instalação nova)

```bash
docker compose up -d        # constrói a imagem e sobe em :5020
```

A imagem (~660 MB) traz o app e o tippecanoe, sem os dados do mapa. A primeira
visita abre o **assistente** (`/setup`, `installer.py`), um cartão por passo
sobre um mapa-múndi leve girando ao fundo (Natural Earth, domínio público,
`static/vendor/world-lite.geojson`):

1. **Idioma** (lista suspensa no topo do primeiro cartão) e **começar do
   zero** ou **restaurar um backup** do servidor (.zip de outra instalação:
   todos os perfis, com visitas, fotos e configurações; serve para migrar).
2. **Perfil** (nome e foto, opcionais) e **vista inicial** (todas as
   visitadas ou onde parei; as outras em Configurações, depois).
3. **Dados do mapa**, montados ali dentro a partir das fontes abertas, com a
   versão mais nova do Overture (ele só mantém as últimas publicadas):
   - **Leve** (~1,9 GB): sem as áreas de cidade do Overture. O contorno de
     cada cidade marcada vem do Nominatim (sai o nome da cidade, o país e as
     coordenadas, uma vez por cidade; desligável em Configurações, e aí a
     cidade fica como pin).
   - **Completo** (~6,3 GB): tudo local.
   Montar leva ~1h a 1h30, ~8 GB de RAM e ~13 GB (Leve) / ~22 GB (Completo) de
   disco temporário. Os temporários (`raw/`, `work/`) são apagados no fim.
4. **Progresso** da montagem. Dá para fechar a página; se o container
   reiniciar no meio, ela continua de onde parou. Erro: "Tentar de novo"
   retoma; log em `/geodata/build.log`.
5. **Onde você já esteve?** (opcional): a lista de cidades, para começar com o
   mapa preenchido. O mapa abre raspando o que foi marcado.

Volumes: `/data` (seus dados; faça backup) e `/geodata` (dados do mapa,
remontáveis). Enquanto o assistente não termina, toda página leva a `/setup`.
O que ele decidiu fica em `data/setup.json`, fora do banco: restaurar um backup
depois não reabre o assistente. Uma instalação de antes do assistente (com os
dados do mapa prontos) é adotada como instalada na subida.

**Testar o assistente sem montar o mapa** (copia os arquivos prontos de outra
instalação, ~1 min):

```bash
docker run -d --name scratch-map-test -p 5030:5020 \
  -v "$PWD/teste/data:/data" -v "$PWD/teste/geodata:/geodata" \
  -v "$PWD/geodata:/seed:ro" -e SCRATCH_BUILD_SIMULATE=/seed scratch-map
```

### Sem Docker

```bash
./setup.sh                                      # venv + geodata
venv/bin/python app.py                          # dev em :5020, com debug
# ou
venv/bin/gunicorn -b 0.0.0.0:5020 app:app       # produção
```

Como serviço (systemd de usuário; o unit supõe o projeto em
`~/projects/scratch-map`, ajuste se for outro lugar):

```bash
cp deploy/scratch-map.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now scratch-map
```

### Configuração

Tudo pela página **Configurações** (engrenagem no Perfil), gravado na tabela
`settings` do `scratch.db` do perfil (vale em todos os aparelhos; cada perfil
tem as suas):

| Chave | Efeito |
|---|---|
| `theme` | `light` / `dark` / `auto` |
| `color_<tipo>` | cor do mapa (`water`, `land`, `country`, `state`, `city`, `airport`, `landmark`); sem a chave, o padrão |
| `start_view` | vista inicial: `country` (cidades visitadas em `home_country`), `all`, `last` (onde parou, por aparelho) ou `fixed` (`start_fixed` = `lon,lat,zoom`). Sem a chave: `country` se houver `home_country`, senão `all` |
| `profile_name`, `profile_photo` | nome e versão da foto do perfil |
| `projection` | `mercator` (plano) ou `globe` |
| `language` | `pt-BR` ou `en`. Sem a chave: no assistente, o do navegador; depois, `pt-BR` |
| `borders_country`, `borders_state`, `borders_city` | `1`/`0`: linha branca entre países, entre estados e em volta das cidades. Sem a chave: países e estados ligados, cidades desligado |
| `skip_animations` | `1`: sem a descida ao abrir e sem a raspagem ao marcar (sem a chave: com animações) |
| `ext_landmark_name`, `ext_city_shape`, `ext_state_flags` | `0` = pedido externo desligado (sem a chave: ligado) |

### No celular (app instalável)

O scratch map é um PWA: no celular, dá para pôr na tela inicial e abrir em
tela cheia, com ícone próprio, como um app. Continua sendo o servidor de casa
mostrando as telas (nada fica guardado no aparelho além da página "sem
conexão", mostrada quando o computador não responde).

- **iPhone** (Safari): Compartilhar → "Adicionar à Tela de Início".
- **Android** (Chrome): menu → "Instalar app".

Para instalar de verdade (e ter o service worker), o Chrome exige **HTTPS**;
em `http://` vira só um atalho (o Safari aceita HTTP). Com Tailscale, dá para
ter HTTPS com o certificado válido que ele emite para o nome da máquina na
tailnet, sem perder o acesso por IP: o `tlsmux.py` fica na porta pública e
olha o primeiro byte de cada conexão (início de handshake TLS → HTTPS com o
certificado; qualquer outro → HTTP), repassando ao gunicorn, que passa a
escutar só em `127.0.0.1:5021`.

| Endereço | |
|---|---|
| `https://<máquina>.<tailnet>.ts.net:5020` | HTTPS sem aviso; é o que instala o app no Android |
| `http://<IP da rede local ou da tailnet>:5020` | HTTP, como sem o tlsmux |
| `https://<IP>:5020` | abre com aviso de certificado (não existe certificado público para IP) |

Para ligar (systemd de usuário):

```bash
deploy/renew-cert.sh        # grava ~/.local/share/scratch-map/tls/{cert,key}.pem
# no scratch-map.service: --bind 127.0.0.1:5021 (veja o comentário no arquivo)
ln -s ~/projects/scratch-map/deploy/scratch-map-{tls.service,cert.service,cert.timer} ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user restart scratch-map
systemctl --user enable --now scratch-map-tls scratch-map-cert.timer
```

O certificado dura 90 dias; o timer `scratch-map-cert` roda o
`renew-cert.sh` todo dia, e o tlsmux relê o certificado quando ele muda
(`systemctl --user reload scratch-map-tls`, sem derrubar conexões). Precisa do
MagicDNS e dos certificados HTTPS ligados no painel do Tailscale, e do seu
usuário como operador (`sudo tailscale set --operator=$USER`). Não publique
com o Funnel: o app não tem senha.

### Outra instância

Para a família, use perfis (acima). Uma instância separada só faz sentido para
dados que não devem nem aparecer na mesma tela de perfis:

```bash
SCRATCH_DATA=/caminho/para/outros-dados venv/bin/gunicorn -b 0.0.0.0:5021 app:app
```

O código e o `geodata/` são compartilhados; cada instância tem sua própria pasta
de dados. No serviço systemd, copie o unit com outro nome, adicione
`Environment=SCRATCH_DATA=…`, troque a porta e inclua o novo caminho em
`ReadWritePaths`.

## Operação

Com Docker:

```bash
docker compose logs -f
docker compose up -d --build            # depois de atualizar o código
```

Com o serviço systemd:

```bash
systemctl --user status scratch-map
journalctl --user -u scratch-map -f
systemctl --user restart scratch-map    # depois de mudar código
```

**Backup**: é do servidor inteiro. Pela tela (Configurações → Backup do
servidor → "Baixar backup"): um `.zip` com **todos os perfis**, cada um em
`profiles/<id>/` com o banco (visitas, monumentos, configurações, contornos),
as fotos (original, exibição e miniatura), as bandeiras baixadas e a foto de
perfil, mais um `manifest.json` com a lista dos perfis. Ficam de fora os
dados do mapa (o assistente monta de novo), o `setup.json` (vale para esta
máquina) e a lixeira de fotos. O banco é copiado pela API de backup do
SQLite, então pode ser feito com o app no ar. A tela mostra quando foi o
último baixado.

**Restaurar**: na mesma tela, ou no primeiro cartão do assistente numa
instalação nova. O servidor confere que é um backup do scratch map
(manifesto, bancos íntegros, só caminhos conhecidos), guarda o estado atual
em `data/backups/antes-de-restaurar-<data>.zip` (ficam as 3 mais recentes) e
troca **todos os perfis** pelos do backup. Para desfazer, restaure essa cópia.
Um backup de antes dos perfis (ou um perfil exportado) vira o único perfil.

**Exportar e importar perfil**: para levar uma pessoa para outra instalação.
Configurações → Perfil → "Exportar este perfil" baixa um `.zip` só com os
dados dele; na outra instalação, "Adicionar perfil" → "Importar um perfil".

Sem a tela: tudo o que importa está em `data/profiles/`. Copiar a pasta com o
serviço parado também serve.

**Fotos apagadas** não somem: vão para `photos/trash/` na pasta do perfil, inclusive as que
saem junto quando você desmarca um lugar. Para limpar, apague a pasta à mão.

## API

Especificação completa (OpenAPI 3.1, com o formato de cada pedido e
resposta): [`docs/openapi.yaml`](docs/openapi.yaml), também navegável no
próprio app em **`/api/docs`** (e o arquivo em `/api/openapi.yaml`, para
importar em outras ferramentas). A tabela abaixo é o resumo.

Para integrações: o perfil é escolhido pelo cookie `perfil=<id>` (com um
perfil só, não precisa), e não há autenticação, então a porta não deve ficar
exposta na internet. Ainda não há versão estável das rotas.

| Método | Rota | O quê |
|---|---|---|
| GET | `/api/visited` | visitados por tipo (explícitos + implícitos), com contagem de fotos |
| PATCH | `/api/settings` | preferências (chaves da tabela em "Configuração"; `null` volta ao padrão); devolve as atuais |
| GET | `/api/backup` | baixa o backup do servidor (.zip com todos os perfis) |
| GET | `/api/backup/info` | perfis, contagens, tamanho e data do último backup |
| GET | `/api/profile/export` | baixa o perfil em uso (.zip, para importar em outra instalação) |
| POST | `/api/profile/import` | preenche um perfil novo com um perfil exportado (multipart `backup`) |
| GET | `/api/countries` | países (para a lista de cidades) e o mais visitado |
| GET | `/api/names` | nome de cada país (no idioma) e estado, para o hover do mapa |
| GET | `/api/cities` | `?country=&state=&q=&offset=`: cidades, maiores primeiro, 50 por vez (e os estados do país na 1ª página) |
| POST | `/api/visits/batch` | `{ids: [...]}`: marca várias cidades; contornos em segundo plano |
| POST | `/api/restore` | troca todos os perfis pelos do backup (multipart `backup`); guarda o estado atual antes |
| GET | `/setup` | assistente de primeira execução (depois de instalado, leva ao mapa) |
| GET | `/api/setup` | estado do assistente e da montagem (etapas, mensagem, erro) |
| POST | `/api/setup/start` | `{mode: "leve" \| "completo"}`: conclui o assistente e começa (ou retoma) a montagem |
| POST | `/api/flags/refetch` | busca de novo as bandeiras de estado (409 se desligadas) |
| POST / DELETE | `/api/profile/photo` | foto de perfil (multipart `photo`) / remove |
| GET | `/manifest.webmanifest`, `/sw.js`, `/offline` | app instalável (PWA) |
| GET | `/api/docs`, `/api/openapi.yaml` | documentação da API |
| DELETE | `/api/profile` | apaga o perfil em uso (move para `data/profiles-removed/`; não o único) |
| GET | `/profiles` | "quem está usando?"; `/profiles/<id>/use` escolhe (cookie `perfil`), `/profiles/<id>/photo.jpg` |
| POST | `/profiles/new` | cria um perfil e abre o assistente para ele |
| GET | `/api/stats` | álbum: países com bandeira (`visited`) e totais por tipo |
| GET | `/api/stats/country/<id>` | estados do país, com cidades visitadas em cada |
| GET | `/api/stats/state/<id>` | cidades do estado (visitadas, depois por população) |
| GET | `/api/city-shapes?ids=` | contornos das cidades visitadas (GeoJSON); com `ids`, só essas. O navegador guarda os que já tem e pede só os de cidades novas; `pending` = ainda há contornos sendo calculados (o mapa pede de novo) |
| GET | `/api/search?q=&kind=city,airport` | busca (sem acento, prefixo primeiro) |
| GET | `/api/nearby?kind=city&lat=&lon=&r=` | mais próximos de um ponto |
| GET | `/api/place/<kind>/<id>` | detalhe: hierarquia, status, "via", `photos` (do lugar; na cidade, + landmarks e aeroportos) e `groups` (estado/país: fotos por cidade contida) |
| GET | `/api/photos` | mural: `recent` (todas, mais recentes primeiro) e `groups` (por localidade) |
| POST | `/api/visits` `{kind, id}` | marca |
| DELETE | `/api/visits/<kind>/<id>` | desmarca (fotos do lugar vão pro trash) |
| POST | `/api/place/<kind>/<id>/photos` | upload multipart (`photos`, opcional `date`) |
| PATCH | `/api/photos/<id>` `{taken_on}` | edita a data |
| DELETE | `/api/photos/<id>` | apaga a foto (vai pro trash); a última foto de um landmark apaga o landmark |
| POST | `/api/landmarks` | cria um rascunho a partir de fotos (multipart `photos`), devolve `{id, gps}` |
| PATCH | `/api/landmarks/<id>` `{name, lat, lon}` | salva nome/posição (tira do rascunho) |
| DELETE | `/api/landmarks/<id>` | apaga o landmark (fotos vão pro trash) |
| GET | `/api/landmarks/near?lat=&lon=` | cidade, estado e país do ponto, com status de visitado |
| GET | `/api/landmarks/suggest?lat=&lon=` | sugestão de nome pelo OSM |

`kind` ∈ `country | state | city | airport` (visitas) e também `landmark`
(fotos, busca, detalhe). Os objetos de `/api/visited`, da busca e do `nearby`
trazem `visited` (conta como visitado) e `explicit` (foi marcado diretamente).

Respostas JSON acima de 2 KB vão com gzip (os contornos de cidade são ~4 MB
crus, ~1 MB comprimidos), o que pesa fora de casa, pela VPN.

## Decisões

- **Implícito calculado, não gravado.** Assim desmarcar uma cidade "desfaz" o
  estado e o país sem precisar de contagem de referências.
- **Monumento não marca nada.** Uma foto numa cachoeira não prova que você foi à
  cidade mais próxima; a escolha fica no formulário.
- **Original preservado.** Cada upload guarda o arquivo original
  (`photos/orig`), uma versão de até 2000 px para exibir e uma miniatura de
  600 px. A orientação EXIF é aplicada nas versões derivadas.
- **Sem tiles externos nem CDN.** Os tiles são um arquivo local; dados e fotos
  ficam só nesta máquina.
- **Uma fonte para país, estado e cidade** (Overture/OSM, recortados pelo mesmo
  litoral) em vez do Natural Earth: com fontes diferentes, as bordas nunca
  coincidiam. O custo é o build pesado (~1h30, ~8 GB de RAM) e até ~6,3 GB em
  `geodata/`. Em vez de hospedar os arquivos prontos, cada instalação monta os
  seus a partir das fontes abertas (assistente de primeira execução).
- **Sem login**, de propósito. Não exponha a porta para a internet. O acesso é
  pela rede local ou por VPN (ex.: Tailscale).

## Licença

Código sob a [licença MIT](LICENSE). Os dados do mapa gerados pelo build
seguem as licenças das fontes (veja "Dados geográficos"); as bandeiras em
`static/vendor/flags/` são do flag-icons (MIT).
