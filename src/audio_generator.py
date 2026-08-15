import os
from pathlib import Path
from pydub import AudioSegment
from elevenlabs.client import ElevenLabs
from dotenv import load_dotenv

load_dotenv()


class AudioGenerator:
    def __init__(self, config=None):
        self.config = config

        self.temp_dir = Path("output/temp/audio")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        api_key = os.getenv("ELEVENLABS_API_KEY")

        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY não configurada no .env")

        self.client = ElevenLabs(api_key=api_key)

        # Vozes
        self.voice_ids = {
            "pt": "bIHbv24MWmeRgasZH58o",
            "en": "pNInz6obpgDQGcFmaJgB",   
            "es": "onwK4e9ZLuTAKqWW03F9"
        }

    def gerar_narracao_completa(self, roteiro, idioma="pt"):
        audios = []

        voice_id = self.voice_ids.get(
            idioma,
            self.voice_ids["pt"]
        )

        for i, cena in enumerate(roteiro["cenas"]):
            ordem = int(cena.get("ordem", i + 1) or (i + 1))

            texto = cena.get("texto_narrador", "").strip()

            if not texto:
                print(f"⚠️ Cena {ordem} sem texto")
                continue

            mp3_path = self.temp_dir / f"narracao_{ordem:02d}.mp3"

            print(f"🎤 Gerando áudio cena {ordem}...")

            try:
                audio_stream = self.client.text_to_speech.convert(
                    text=texto,
                    voice_id=voice_id,
                    model_id="eleven_multilingual_v2",
                    output_format="mp3_44100_128"
                )

                audio_bytes = b"".join(audio_stream)

                with open(mp3_path, "wb") as f:
                    f.write(audio_bytes)

                # Normaliza volume
                audio_segment = AudioSegment.from_mp3(mp3_path)
                audio_segment = audio_segment.normalize()

                audio_segment.export(
                    mp3_path,
                    format="mp3"
                )

                audios.append({
                    "path": str(mp3_path),
                    "duracao": len(audio_segment) / 1000.0,
                    "ordem": ordem
                })

            except Exception as e:
                print(f"❌ Erro na cena {ordem}: {e}")

        print(f"✅ {len(audios)} áudios gerados")

        return audios


# -------------------------
# 🚀 EXECUÇÃO
# -------------------------

if __name__ == "__main__":

    roteiro = {
        "cenas": [
            {
                "texto_narrador": "A inteligência artificial está mudando o mundo."
            },
            {
                "texto_narrador": "Essas ferramentas parecem ilegais de tão poderosas."
            }
        ]
    }

    generator = AudioGenerator()

    audios = generator.gerar_narracao_completa(
        roteiro,
        idioma="pt"
    )

    for a in audios:
        print(a)