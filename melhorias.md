# Melhorias

Lista de alterações pedidas. Ficam em "Pendentes" até serem implementadas juntas.

## Pendentes

- **Instalável, com assistente de primeira execução** (no estilo do Home
  Assistant Core). **Em andamento** (item 38: container Docker, assistente e
  modo Leve, testados com a montagem simulada). Falta: validar uma montagem
  real do zero na máquina de destino; ajuste fino das telas; idioma quando
  houver tradução. Ideia original: instala e sobe com uma interface simples onde se fazem as
  configurações iniciais e se escolhem os defaults; depois ele baixa o que
  precisa em segundo plano, mostrando o progresso. Configurações iniciais:
  - idioma (ver tradução abaixo);
  - vista inicial do mapa (já existe na configuração, item 32);
  - dados do mapa locais (opcional): baixar/gerar o conteúdo pesado (tiles,
    áreas de cidade, litoral, ~6 GB e ~1h30 de build) ou não. Sem eles, o app
    usa pedidos externos como fallback (tiles de um servidor público e
    contorno de cidade pelo Nominatim), com aviso claro de que isso tem algum
    nível de vazamento de dados (quem responde vê quais lugares são
    consultados e o IP). Baixar depois também é pela instalação, não pela
    tela de configuração do app (a do botão na barra de menu).
- **Nomes de lugares na tradução** (a interface já tem PT-BR e EN, item 41):
  hoje países e estados aparecem em português também em inglês ("Brasil",
  "Alemanha"), porque o build guarda o nome em português. Ideia original:
  nomes de lugares **não** seguem o idioma da interface: ficam no nome original
  quando ele é escrito em alfabeto latino (inclui diacríticos, como croata,
  nórdicos etc.) e transliterados para o latino quando o alfabeto é muito
  diferente (grego, cirílico, japonês, chinês, árabe e similares). O Overture
  tem o nome original (`names.primary`, hoje o build guarda só pt/en) e, para
  alguns lugares, formas já transliteradas; no resto, transliterar no build.
- **Modo ultra-leve** (a discutir): um terceiro modo de dados, sem contorno
  de cidade nenhum; as cidades ficam só como pin. Ficaria com ~0,7 GB no fim
  (o `world.pmtiles` de 671 MB + o `geo.db`), contra ~1,9 GB do Leve: o
  `land.parquet` (1,2 GB) só serve para recortar o contorno da cidade pelo
  litoral, então sai junto. Bônus: nenhum pedido ao Nominatim (privado e
  funciona sem internet, como o Completo). A montagem não fica mais rápida
  nem pede menos memória: o litoral ainda é baixado e usado para recortar
  países e estados (só não é guardado no fim). A discutir: vale a perda do
  contorno (a cidade é o que mais aparece no mapa), e se dá para trocar de
  modo depois (hoje não dá).
- **Múltiplos usuários** (a discutir; ainda não está claro como funcionaria).
  Caminhos possíveis, do mais simples ao mais completo:
  - **Uma instância por pessoa** (já funciona hoje: outro `SCRATCH_DATA` e
    outra porta, os dados do mapa compartilhados; no Docker, outro container
    com outro volume `/data`). Cada um no seu endereço, nada em comum.
  - **Perfis sem senha** na mesma instância, estilo "quem está usando?" da
    Netflix: escolhe o perfil ao abrir, cada um com suas visitas, fotos e
    configurações. Confia em quem está na rede (como hoje). Dá para guardar
    cada perfil numa pasta de dados própria (backup por pessoa continua
    simples) ou no mesmo banco com uma coluna de usuário.
  - **Contas com login** (senha ou passkey): necessário se um dia o app sair
    da rede de casa; bem mais trabalho (sessões, recuperação de acesso).
  Perguntas em aberto: viagem em família marca para todos de uma vez? Fotos
  são compartilhadas ou de cada um? Um mapa comparando ("onde fomos
  juntos", "onde só eu fui")? Configurações (tema, idioma) por pessoa ou da
  casa toda?
- **Toggles das camadas na nova navegação**: continuam na barra superior, como
  antes; onde eles ficam ainda está em aberto.
- **Bandeiras de cidades no Stats** (estados já têm, item 29; cidade hoje
  mostra as iniciais): Wikidata (propriedade "bandeira", P41), ligando pela
  propriedade do id do GeoNames (P1566), já que as cidades vêm dele. Mesmo
  esquema dos estados: baixar em segundo plano por estado ou país visitado,
  miniatura em `data/flags/`. Muitas cidades não têm bandeira cadastrada:
  essas continuam com as iniciais.
- **Dados baixados em execução, em lotes** (a discutir): em vez de tudo no
  build ou na instalação, alguns dados podem vir aos poucos, em segundo plano,
  conforme o uso. Já é assim com as bandeiras de estado (item 29); daria para
  estender às bandeiras de cidades e a outros dados pesados.
- **Mais configurações** (a tela existe: tema, cores, formato, vista inicial,
  dados e privacidade): idioma (quando houver tradução). **A discutir**:
  camadas ligadas ao abrir (junto com a decisão dos toggles), duração/pular a
  raspagem (por enquanto fica fixa em 5 s), backup automático periódico (hoje
  só manual).

## Feitas

### 2026-10-16
38. **Container Docker e assistente de primeira execução** (em andamento):
    `Dockerfile` + `docker-compose.yml` (volumes `/data` e `/geodata`, porta
    5020). A imagem não traz os dados do mapa: a primeira visita abre
    `/setup` (começar do zero ou restaurar um backup → idioma → perfil → vista
    inicial → dados do mapa → progresso), e a montagem roda ali dentro, a
    partir das mesmas fontes abertas do build (sem hospedar nada), com a
    versão mais nova do Overture. **Modo Leve** (~1,9 GB, sem as áreas de
    cidade; o contorno da cidade vem do Nominatim, com aviso e desligável) ou
    **Completo** (~6,3 GB, tudo local). Retomável se o container reiniciar.
    A instância atual (systemd) é adotada como instalada e não muda.
    Visual: ao abrir, um mapa-múndi leve (Natural Earth, em
    `static/vendor/world-lite.geojson`, porque os dados do mapa ainda não
    existem) gira devagar para leste; em ~1,6 s ele desfoca e um cartão
    branco aparece. Cada passo é esse cartão, com troca deslizando (para
    trás no "Voltar") e a altura acompanhando o conteúdo.
39. **Lista de cidades (marcar em lote)**: para registrar o histórico sem
    buscar uma por uma. País (o mais visitado, ou o do idioma do navegador) →
    estado (opcional) → cidades das maiores para as menores, 50 por vez, com
    filtro por nome; tocar escolhe, e a escolha vale ao trocar de país. Está
    no fim do assistente ("Marcar as cidades que você já conhece", depois de
    montar o mapa) e no + do mapa ("Lista de cidades"). Marcadas, o mapa faz
    **uma cena só**: enquadra as cidades novas e raspa países, estados e
    cidades juntos. Os contornos são calculados em segundo plano (no modo
    leve, 1 por segundo pelo Nominatim) e o mapa vai buscando os prontos: a
    cidade sai do pin e ganha a cor. Um cálculo de contornos por vez no
    servidor (um pedido no meio de outro espera a vez).
40. **Bordas configuráveis**: Configurações → Mapa → Bordas, com
    liga/desliga para a linha branca entre países, entre estados e em volta
    das cidades visitadas (antes a cidade tinha um contorno roxo, que quase
    não se via; agora é branco como os outros, desligado por padrão). A cor
    da borda não é configurável por enquanto: ela é um branco translúcido
    (que funciona sobre qualquer cor) e o seletor de cor não tem
    transparência.
41. **Tradução para inglês e "Monumento"**: os textos da interface passaram
    por `i18n.py` (templates com `_()`, JS com `SM.t()`, mensagens do
    servidor com `tr()`), com o português como chave e `i18n/en.json` com as
    ~250 traduções. "Landmark" virou **Monumento** em português (em inglês
    continua Landmark). O idioma é o primeiro item do assistente (no cartão
    de boas-vindas; trocar recarrega já traduzido, sem repetir a entrada) e
    fica em Configurações → Aparência. Sem escolha: no assistente, o do
    navegador; numa instalação que já existia, português. Ficam sem
    tradução as mensagens técnicas da montagem (log) e os nomes de lugares.
42. **Idioma em lista suspensa e nome do país no hover**: o idioma virou uma
    lista suspensa (no assistente e em Configurações), pronta para mais
    idiomas. No mapa, com as bordas de estado desligadas (ou de longe, abaixo
    do zoom 2,5, onde a divisa nem aparece), passar o mouse ou tocar num
    estado não visitado mostra e abre o **país**, não o estado; estado
    visitado (pintado) continua respondendo como estado.

### 2026-10-15
22. **Barra de menu na base, estilo liquid glass**: abas Mapa, Mural e Stats,
    botão + e, separado à direita, o de configuração (desativado por
    enquanto). Substitui o link "🖼️ Mural" do topo e o "← Mapa" do mural.
    Cada aba é uma página (trocar recarrega o mapa).
23. **Sem painel lateral; tudo numa gaveta**: o mapa ocupa a tela toda. A
    gaveta sobe de baixo, cobre a barra e trava o mapa (véu); tocar fora,
    arrastar a alça para baixo, × ou Esc recolhem, e ‹ volta. Ela mostra:
    - **Adicionar** (+): Cidade (busca + bandeira), Landmark (a partir de
      foto) e Foto (busca o lugar, escolhe os arquivos, abre o lugar);
    - **o lugar**, ao tocar no mapa (mesmo conteúdo de antes);
    - **o formulário do landmark**, mais baixo e sem véu, porque usa o mapa
      para posicionar.
    A lista de visitados foi para **Stats**. A busca geral saiu: estado, país
    e aeroporto se marcam tocando no mapa (lista "perto de onde você tocou").
24. **Raspagem ao marcar**: cidade, estado ou país que passa a ser visitado não
    ganha a cor de uma vez. Um retrato do mapa de antes, recortado no formato
    do lugar, vira a película, raspada em zigue-zague de cima para baixo em
    5 s (`SCRATCH_MS` em `static/app.js`), com borda irregular e lascas caindo.
    Vale para qualquer marcação (bandeira, "Estive aqui", "também marcar" do
    landmark, foto num lugar novo). Com "reduzir movimento" ligado no sistema,
    a cor aparece direto.
25. **Cena ao marcar**: a marcação é gravada na hora; a cena só mostra. Os
    lugares novos entram um a um, do maior para o menor (país → estado →
    cidade): a gaveta sai, o mapa enquadra o lugar, a película é raspada, e
    assim por diante. No fim a gaveta volta, com a cidade enquadrada acima
    dela. "Toque para pular" termina tudo na hora. Primeira cidade num país
    novo: ~25 s (3 raspagens de 5 s + voos).
26. **Gaveta flutuante com foto**: mais estreita que a tela, com folga embaixo
    e cantos arredondados. Lugar com foto: a mais recente horizontal (vertical
    só se não houver) vira o topo, de ponta a ponta, com o nome sobre um
    desfoque leve; × e ‹ viram botões de vidro sobre a foto. Abre só com a
    altura da foto; arrastar para cima ou tocar na alça expande.
27. **Desmarcar demorava**: toda recarga dos visitados baixava de novo os
    contornos de todas as cidades (~4 MB), lento pela tailnet (relay). Agora o
    navegador guarda os contornos e pede só os de cidades novas
    (`/api/city-shapes?ids=`), e o servidor manda JSON com gzip (~1 MB na
    primeira carga).
28. **Stats como álbum de bandeiras**: totais no topo e os países como
    círculos (44 px) com a bandeira, visitados em cor cheia e os outros bem
    apagados (cinza, 30%). As listas de não visitados começam dobradas (~3
    linhas, com fade) e o "Ver mais" abre. Tocar num país mostra os estados
    dele; num estado, as cidades (visitadas, depois as maiores); numa cidade,
    abre no mapa. Endereço com `#BR` / `#BR/BR-SP` (o voltar do navegador
    funciona). Bandeiras do flag-icons (MIT), quadradas, em
    `static/vendor/flags/`: 250 países e 10 subdivisões que o pacote traz
    (Catalunha, Galícia, País Basco, Inglaterra, Escócia, Gales, Irlanda do
    Norte, Santa Helena…). Sem bandeira: sigla (BR-SP → SP; cidade pelas
    iniciais) na cor do tipo. Aeroportos e landmarks ficam em lista no fim.
    Os territórios disputados `X*` do Overture não entram no álbum.
29. **Bandeiras de estado**: quando um país passa a ser visitado (e na subida
    do serviço, para os já visitados), `flags.py` baixa em segundo plano, do
    Wikidata/Commons, as bandeiras dos estados dele (pelo código ISO 3166-2)
    para `data/flags/<ID>.webp`. Uma vez por país; com limite de requisições
    (429), espera e tenta de novo. Brasil: 27 de 27, 140 KB. Sem bandeira no
    Wikidata: sigla, como antes. Sai da máquina só o código do país e os nomes
    dos arquivos das bandeiras.
30. **Sem pin nas cidades**: a bolinha roxa sobre a cidade saiu (e com ela a
    regra de sumir ao aproximar, item 7); a cidade aparece só pelo contorno
    preenchido. O pin fica apenas para cidade sem contorno, que senão sumiria
    do mapa (hoje nenhuma das visitadas).
31. **Perfil e configurações**: a aba Stats virou **Perfil** (ícone de pessoa):
    nome e foto de perfil no topo, editáveis ali, e o álbum abaixo. A
    engrenagem no cabeçalho do Perfil abre **Configurações** (a barra ficou
    só com Mapa, Mural, Perfil e +, centralizados), por enquanto só
    Aparência: tema claro/escuro/automático (as fotos impressas continuam
    papel branco) e as cores do mapa por tipo, com prévia ao vivo e
    "Restaurar cores padrão". Salvo no servidor (tabela `settings`): vale no
    PC e no iPhone.
32. **Vista inicial na configuração**: o país "de casa" (antes editado à mão
    no banco, e só servia para isso) virou uma das opções. Opções: cidades
    visitadas num país (entre os visitados), todas as visitadas, onde parei
    (por aparelho) ou posição fixa, escolhida arrastando um mapa pequeno na
    própria página.
33. **Formato do mapa e Dados e privacidade**: plano ou globo passou a ser
    configuração (o botão 🌍 do topo saiu). Nova seção com liga/desliga para
    cada pedido que sai da máquina, explicando o que sai e para quem:
    sugestão de nome do landmark (Nominatim), contorno de cidade de exceção
    (Nominatim; desligado, a cidade fica com pin e tenta de novo quando
    religar) e bandeiras de estado (Wikidata/Commons; desligado, as já
    baixadas ficam), com "Buscar bandeiras de novo". Foto num lugar novo
    também passou a disparar a busca das bandeiras.
34. **Backup**: em Configurações, "Baixar backup" gera um .zip com banco,
    fotos, bandeiras e foto de perfil (~66 MB hoje), e mostra quando foi o
    último. "Restaurar" confere o arquivo (manifesto, banco íntegro, só
    caminhos conhecidos), guarda o estado atual em `data/backups/` (5
    últimas) e troca tudo.
35. **Folga no fim das páginas e gavetas**: no Perfil, nas Configurações e no
    Mural o último conteúdo ficava embaixo da barra (o body tinha altura fixa
    e a folga do fim não entrava na rolagem). Agora essas páginas crescem com
    o conteúdo e param ~34 px acima da barra; as gavetas ganharam mais folga
    embaixo.
36. **Gaveta pulava para cheia ao abrir e fechar**: ao abrir, animava da
    altura cheia (guardada da vez anterior) até a da foto; ao fechar, a altura
    era limpa na hora e ela crescia enquanto descia. Agora abre já no tamanho
    certo e desce com o tamanho que tem (a altura é limpa depois que sai da
    tela).
37. **Mural: linha do tempo, sem quebras, mesa clara**: "Mais recentes" virou
    **Linha do tempo**, com uma etiqueta por mês (a do primeiro mês de cada
    ano em amarelo) e as sem data no fim. Nos dois modos os rótulos viraram
    etiquetas de papel (com fita) dentro da grade, como mais uma vaga, em vez
    de títulos que quebravam a linha. A mesa passou para madeira clara
    (carvalho); no tema escuro, a escura de antes.
    Depois: botão para inverter a linha do tempo (mais novas ou mais antigas
    primeiro, salvo no navegador; sem data sempre no fim) e mesa num tom mais
    nude (bege rosado, veios mais suaves).

### 2026-10-07
1. **Fundo do modo globo**: espaço escuro (gradiente azul-noite) em volta do
   globo, com halo de atmosfera que some ao aproximar.
2. **Cores mais escuras**: água `#86b9dc`, terra não visitada verde `#8db37c`,
   fronteiras brancas translúcidas. Aeroporto passou a azul-marinho para
   contrastar com o verde.
3. **"+ fui" virou bandeira azul**: contorno = não visitado, cheia = visitado.
   Na tela do lugar o botão é "🏳 Estive aqui".
4. **Aeroporto com ícone de avião**: no mapa (com contorno branco) e nas
   legendas/listas (máscara CSS com o mesmo desenho).
5. **Cidade com limites preenchidos**: contorno do município via
   OpenStreetMap/Nominatim, buscado uma vez e guardado localmente
   (`boundaries.py`, tabela `city_shapes`). O pin some ao aproximar quando há
   contorno. Para o contorno não destoar da costa, os polígonos de
   país/estado ganharam mais detalhe (40%/25% dos vértices).

### 2026-10-08
6. **Gaveta do celular**: 3 alturas (mínima = alça + busca, meia, cheia).
   Arrasta pela alça (área de toque maior) ou toca para alternar; tocar no mar
   minimiza; focar a busca com a gaveta mínima sobe para meia.
7. **Cidade sem pin**: o pin só aparece enquanto o contorno tem menos de 14 px
   na tela (zoom calculado por cidade, com transição suave) e não pega clique
   depois de sumir. Cidade sem contorno mantém o pin.
8. **Toggles no lugar das abas** (experimento): 4 botões liga/desliga com
   contagem, salvos no navegador. O painel agrupa os visitados por tipo. O
   clique no mapa abre o mais específico entre as camadas ligadas e, num
   estado/país, lista cidades e aeroportos perto do toque para marcar.
   As abas foram removidas; se não ficar bom, dá para voltar a elas.

### 2026-10-08 (2)
9. **Visitado é visitado**: sem distinção entre marcado direto e via cidade.
   Saiu a etiqueta "via cidade", o status é só "Visitado ✓", saiu a seção
   "Marcado por" e a bandeira fica cheia para estado/país marcados por cidade.
   Tocar nela (ou em "Desmarcar") mostra um aviso: o estado está marcado pelas
   suas cidades e só sai desmarcando as cidades.
10. **Landmarks**: pontos criados só a partir de foto ("Novo landmark a partir
    de foto"). A posição vem do GPS da foto (EXIF); sem GPS, toca-se no mapa.
    O marcador é arrastável. O nome é sugerido pelo OpenStreetMap (só as
    coordenadas saem). Não marcam nada sozinhos: o formulário oferece "também
    marcar" a cidade mais próxima, o estado e o país, tudo desmarcado. No mapa é
    uma estrela verde-petróleo de longe e, a partir do zoom 6, a miniatura da
    foto impressa. 5º toggle no topo. Apagar a última foto apaga o landmark.
    No celular, os toggles ficam só com ícone + contagem.
11. **Desselecionar**: o "← voltar" virou um "✕" no canto da tela do lugar, que
    tira o destaque do mapa e volta para a lista inicial (ou para a busca, se
    veio dela). Tocar no mar e Esc fazem o mesmo.

### 2026-10-08 (3)
12. **Fotos do landmark na cidade**: a tela da cidade mostra as fotos dela e as
    dos landmarks dela, misturadas, com o nome do landmark na margem. No
    lightbox, "Abrir <landmark>". A contagem 📷 da cidade inclui essas fotos.
13. **Miniatura do landmark só de perto**: entra no zoom 8 (antes 6) e ficou
    menor (44 px).
14. **Landmark com ícone de alfinete** (map-pin com furo) no lugar da estrela.
15. **Mural** (`/mural`, link "🖼️ Mural" no topo): todas as fotos impressas
    sobre uma mesa de madeira, inclinação/deslocamento fixos por foto, sem
    sobrepor. Duas ordens (salvas no navegador): mais recentes primeiro, ou
    por localidade (cidade em ordem alfabética; landmark entra pela cidade
    dele, aeroporto pela cidade mais próxima; foto de estado/país vira o grupo
    "Nome (estado)"/"Nome (país)"). Lightbox com setas por todo o mural e
    "Abrir <lugar>", que leva ao mapa (`/?open=kind:id`).
16. **Fotos sobem na hierarquia**: estado e país mostram as próprias fotos e,
    abaixo, um grupo por cidade contida (título clicável; no país, "Cidade ·
    Estado"). Só exibição: apagar/mudar a data altera a foto original. A
    contagem de estado/país continua só a do próprio lugar.
    Junto: as fotos de cada lugar passaram a vir das mais recentes para as mais
    antigas, como no mural.

### 2026-10-09
17. **Foto de aeroporto na cidade**: a tela da cidade passou a mostrar também
    as fotos dos aeroportos dela (antes só as dos landmarks), como já fazia o
    grupo da cidade no estado/país e no mural. A contagem 📷 inclui essas fotos.
18. **Contornos de país e estado iguais**: antes vinham de arquivos diferentes
    do Natural Earth, simplificados em proporções diferentes (países 40%,
    estados 25%), e a fronteira comum não se sobrepunha. Agora só os estados
    são simplificados (60%, precisão ~10 m) e cada país é a união dos seus
    estados, então a borda é a mesma linha. Download foi de ~3 para ~6,9 MB
    (gzip, só na 1ª visita). Para voltar: `SIMPLIFY` em
    `scripts/build_geodata.py` e `--polygons-only`; os arquivos antigos estão
    em `geodata/bak-2026-10-08/` (copiar para `static/geo/` e reiniciar).

### 2026-10-09 (2)
19. **País, estado e cidade da mesma fonte**: Natural Earth e Nominatim saíram;
    tudo vem do Overture Maps (dados do OSM), recortado pelo mesmo litoral do
    OSM (land polygons), então costa e divisas coincidem nas três camadas.
    - Países e estados: tiles vetoriais (`geodata/world.pmtiles`, 703 MB,
      zoom 0–12); o navegador baixa só os pedaços na tela (~0,4–1,3 MB ao
      abrir, antes 6,9 MB). Zoom máximo do mapa foi de 9 para 14.
    - Cidades: contorno calculado na hora de marcar, a partir de arquivos
      locais (`geodata/localities/`, `land.parquet`). Nada mais sai da máquina
      (só a sugestão de nome do landmark, que continua no Nominatim).
    - ids novos: estado ISO 3166-2 (`BR-RJ`), país ISO (`BR`).
      `scripts/migrate_ids.py` converteu as visitas (Brasil e Espírito Santo
      marcados direto) e recalculou os 48 contornos de cidade.
    - Enquadramento ignora ilhas distantes (Trindade no ES e em Vitória).
    - Disco: ~6,3 GB usados pelo app em `geodata/` (tiles 0,7 + áreas de
      cidade 4,4 + litoral 1,2) e ~15 GB de downloads/intermediários do build
      em `raw/` e `work/`, que dá para apagar. Build: ~1h30 num notebook de 8 GB.
20. **Brasília com contorno do Nominatim**: a única área do Overture que contém
    Brasília ("Plano Piloto") é uma cópia do contorno do DF inteiro. Área de
    cidade igual ao estado agora é descartada (regra geral) e, nesse caso, o
    contorno é pedido uma vez ao Nominatim (Brasília → Plano Piloto, ~450 km²) e
    recortado pelo mesmo litoral. Ressalva no README para ajuste futuro.
21. **Vista inicial nas cidades do país "de casa"**: o mapa abre enquadrando
    as cidades visitadas no país configurado em `settings.home_country` (aqui,
    `BR`); sem ele, todas as visitadas. Vale no celular e no computador; link
    `/?open=` continua abrindo o lugar.
