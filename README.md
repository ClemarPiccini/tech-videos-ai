README_MD = '''# 🎬 Tech Video AI Generator

Sistema automatizado de geração de vídeos dark sobre tecnologia para YouTube em múltiplos idiomas.

## 🚀 Funcionalidades

- ✅ Geração automática de roteiros virais com Claude AI
- 🎤 Narração em português, espanhol e inglês
- 🖼️ Busca e processamento automático de imagens
- 🎨 Efeitos dark/tech/cyberpunk
- 📤 Upload automático para YouTube
- 📊 Histórico de vídeos publicados

## 📦 Instalação

```bash
# Clone o repositório
git clone <seu-repo>
cd tech-video-ai

# Instale as dependências
pip install -r requirements.txt

# Configure a estrutura
python scripts/setup.py
```

## ⚙️ Configuração

### 1. Chaves de API

Crie o arquivo `.env`:

```env
ANTHROPIC_API_KEY=sua_chave_aqui
UNSPLASH_API_KEY=sua_chave_aqui (opcional)
PEXELS_API_KEY=sua_chave_aqui (opcional)
```

### 2. YouTube API

```bash
python scripts/authenticate_youtube.py
```

Siga as instruções para autenticar.

## 🎯 Uso

### Gerar um vídeo

```bash
python src/main.py --tema "IA que prevê o futuro" --idioma pt
```

### Gerar e fazer upload

```bash
python src/main.py --tema "Hackers famosos" --idioma pt --upload
```

### Modo batch (múltiplos vídeos)

```bash
python src/main.py --batch 5 --idioma pt --upload
```

### Teste sem upload

```bash
python src/main.py --tema "Cibersegurança" --idioma pt --test
```

## 📁 Estrutura do Projeto

```
tech-video-ai/
├── src/               # Código fonte
├── assets/            # Fontes, músicas, imagens
├── output/            # Vídeos gerados
├── data/              # Temas e logs
├── credentials/       # Credenciais API
└── scripts/           # Scripts auxiliares
```

## 🎨 Personalização

Edite `config.yaml` para ajustar:

- Resolução e FPS
- Efeitos visuais
- Volume de áudio
- Temas disponíveis
- Configurações de upload

## 📝 Temas Disponíveis

Os temas estão em `data/temas_tech.json`. Adicione seus próprios temas!

## 🤝 Contribuindo

Pull requests são bem-vindos!

## 📄 Licença

MIT License

## ⚠️ Avisos

- Respeite direitos autorais das imagens
- Verifique termos de uso das APIs
- Conteúdo gerado por IA pode precisar de revisão
- Siga as políticas do YouTube
