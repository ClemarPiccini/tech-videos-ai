# Dark Video Studio

Gera vídeos prontos para postar no estilo de canal "dark": narração, vídeos stock, legendas animadas, música, thumbnail, título, descrição e hashtags. Você preenche um formulário no navegador e recebe o vídeo final.

```
Ideia + presets ──► Claude (roteiro) ──► Narração (Edge TTS / ElevenLabs)
                                    ──► Mídia stock (Pixabay / Pexels / Openverse) ──► ffmpeg ──► video.mp4
                                                                          thumbnail.jpg
                                                                          post.txt / metadata.json
```

## Requisitos

- Python 3.9 ou mais novo
- `ffmpeg` no PATH (`brew install ffmpeg`)
- Uma IA para escrever o roteiro. Escolha em **⚙ Configurações** na interface:
  - **IA local grátis**: instale o [Ollama](https://ollama.com/download), abra o app e baixe um modelo pela própria tela de Configurações. O padrão é o `qwen2.5:7b` (~4,7 GB). Com 16 GB de RAM ou mais, o `qwen2.5:14b` escreve melhor. Vídeos longos são escritos em partes (esboço + uma chamada por parte), porque modelos pequenos não produzem 1.500 palavras de uma vez.
  - **Claude**: cole sua chave da Anthropic em Configurações. A qualidade é bem superior, e o custo é de centavos por roteiro.
  - **Automático** (padrão): usa o Claude se houver chave e cai para a IA local se a conta estiver sem crédito.
- Chaves no `.env` (copie o `.env.example`) ou direto na tela de Configurações:
  - `ANTHROPIC_API_KEY`: opcional se você usar a IA local
  - `PIXABAY_API_KEY`: recomendada, grátis em <https://pixabay.com/api/docs/>. Libera vídeos stock.
  - `PEXELS_API_KEY`: opcional, só se você já tiver uma chave.
  - `ELEVENLABS_API_KEY`: opcional, para a voz premium. O Edge TTS é gratuito e não precisa de chave.

  Sem nenhuma chave de mídia, o app usa fotos em domínio público do [Openverse](https://openverse.org) com zoom lento (efeito Ken Burns). Fica bom, mas é menos dinâmico que vídeo. A ordem de busca é: vídeos (Pexels → Pixabay), depois fotos (Pexels → Pixabay → Openverse) e, por último, um fundo gerado. Cada vídeo salva um `credits.txt` com a origem de cada clipe. O Pixabay pede que a fonte seja citada, então vale colar esses créditos na descrição.

## Instalação

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # e preencha as chaves
```

## Uso

```bash
.venv/bin/python -m app.cli serve
# abra http://127.0.0.1:8000
```

Na interface você escolhe:

| Campo | Opções |
|---|---|
| Ideia | Texto livre. Vazio = o Claude escolhe um tema viral do nicho. 🎲 sugere uma ideia. |
| Nicho | Mistérios, terror, crimes reais, curiosidades, tecnologia sombria, espaço, história, lendas, bíblico, estoicismo |
| Plataforma | YouTube 16:9, Shorts, TikTok ou Reels (9:16) |
| Duração | Opções prontas por plataforma, ou valor livre em segundos |
| Idioma / tom / voz | pt, es, en · misterioso, assustador, documental, épico, suspense |
| Extras | Legendas animadas, música de fundo, CTA no final, instruções livres |

Cada vídeo fica em `output/<id>/`, com `video.mp4`, `thumbnail.jpg`, `post.txt` (título, descrição e hashtags para colar) e `script.json`.

### Linha de comando

```bash
.venv/bin/python -m app.cli generate --prompt "O navio encontrado sem tripulantes" --platform shorts --duration 60
```

### Publicar no YouTube

1. No Google Cloud, crie credenciais OAuth (tipo "App para computador") com a YouTube Data API v3 habilitada.
2. Salve o JSON em `credentials/youtube_credentials.json`.
3. Rode `.venv/bin/python -m scripts.authenticate_youtube` uma vez, ou clique em **Enviar** na interface.

O upload marca o vídeo como conteúdo sintético (`containsSyntheticMedia`), como o YouTube exige para mídia realista gerada por IA. TikTok e Reels: baixe o vídeo e poste pelo app.

## Roteiro guiado

Na interface, escolha **Roteiro guiado** e preencha Tema, Gancho, Fatos obrigatórios, Virada e Final. Também dá para colar um briefing inteiro em qualquer campo de texto, e os campos se preenchem sozinhos:

```
TEMA: O navio Mary Celeste, encontrado à deriva no Atlântico em dezembro de 1872.
GANCHO: "Em 1872, um navio foi encontrado navegando sozinho no meio do oceano. Não havia ninguém a bordo."
FATOS OBRIGATÓRIOS:
- 10 pessoas a bordo, incluindo o capitão, a esposa e a filha de 2 anos
- Comida e água para 6 meses intactas
VIRADA: Não havia sinal de luta, roubo ou tempestade.
FINAL: Terminar com a pergunta: "O que faria 10 pessoas abandonarem um navio perfeitamente seguro?"
```

O que o app garante, independentemente da IA:
- **Gancho e final literais:** o vídeo abre com o gancho e fecha com o final exatamente como você escreveu, e qualquer CTA que a IA acrescente depois do final é cortado.
- **Fatos obrigatórios:** cada fato é conferido no texto, incluindo os números (10, dez etc.). Se faltar algum, a IA tenta corrigir; se ainda faltar, o fato entra com as suas palavras.
- **Nenhum fato extra:** o prompt proíbe acrescentar datas, números, nomes ou teorias que não estejam no briefing.
- **Duração recomendada:** a interface avisa quando o briefing não cabe na duração escolhida e sugere uma.
- **Com IA local:** a estrutura é fixa (abertura, uma cena por fato, virada, final) e o modelo só escreve o texto de cada cena. Isso evita que um modelo pequeno repita ou embaralhe os fatos.

## Instagram Reels (plataforma padrão)

O Reels é a plataforma padrão. YouTube, Shorts e TikTok também aparecem na interface; para esconder alguma, use `enabled: false` em `presets.yaml`.

- **Duração:** o roteiro é calculado pela velocidade medida da voz (`narration.words_per_second`). Se a narração passar do tempo pedido, o áudio é acelerado em até 1,2× (`max_speedup`), sem mudar o tom. Com a IA local, o roteiro também é reescrito quando sai fora da faixa de 80% a 120% do tamanho.
- **Imagens:** cada busca é limpa de termos abstratos ("mystery", "theory"…). Primeiro tenta-se com o assunto do vídeo junto (ex.: `dimly lit room hospital`), e só são aceitos resultados cujas tags contenham o substantivo principal. O filtro de clima (`video.max_source_brightness`) descarta clipes claros demais olhando a miniatura antes de baixar.
- **Post:** `post.txt` traz a legenda pronta (gancho na 1ª linha) e no máximo 5 hashtags, o limite atual do Instagram. A legenda animada fica fora da área coberta pelos botões e pela legenda do post. O texto da capa fica no centro, que é o que aparece no recorte 4:5 do perfil.

## Personalização

- `presets.yaml`: nichos, ideias, tons, durações por plataforma e vozes. É lido a cada requisição, então não precisa reiniciar o servidor.
- `config.yaml`: modelo do Claude, correção de cor, fps, volume e ducking da música, fonte e cores das legendas.
- `assets/music/`: uma faixa é escolhida aleatoriamente por vídeo. Use apenas músicas com licença para uso comercial.

## Estrutura

```
app/
  server.py          API + interface (FastAPI)
  jobs.py            fila de geração em background
  cli.py             serve / generate
  models.py          VideoRequest, VideoScript
  pipeline/
    script.py        roteiro com Claude ou IA local (saída estruturada)
    ollama.py        cliente do Ollama (modelos locais, download)
    tts.py           Edge TTS / ElevenLabs com tempo por palavra
    visuals.py       busca e cache de mídia (Pixabay, Pexels, Openverse)
    captions.py      legendas estilo viral (PNG + overlay)
    render.py        montagem e mix com ffmpeg
    thumbnail.py     thumbnail com texto
    runner.py        orquestra tudo
  publish/youtube.py upload
  static/            interface web
```

## Testes

```bash
.venv/bin/python -m pytest
```

Os testes rodam sem chaves de API. O `tests/test_render.py` monta um vídeo completo com ffmpeg usando áudio e vídeo sintéticos.

## Monetização: o que o YouTube cobra

O Programa de Parcerias do YouTube não monetiza conteúdo "repetitivo ou produzido em massa". Canais que só empilham vídeos gerados automaticamente costumam ser recusados. Para aumentar as chances de aprovação:

- revise e edite o roteiro (`script.json`) antes de publicar;
- mantenha a precisão em temas reais (o prompt já orienta o Claude a separar fato de especulação);
- varie formatos e temas;
- use vozes e músicas com licença comercial.
