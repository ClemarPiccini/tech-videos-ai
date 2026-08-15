from pathlib import Path
from moviepy.editor import *
from moviepy.video.fx import all as vfx
import numpy as np

class VideoEditor:
    def __init__(self, config):
        self.config = config
        self.output_dir = Path("output/videos")
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def montar_video(self, roteiro, audios, imagens, idioma):
        clips = []
        cenas = sorted(roteiro['cenas'], key=lambda c: int(c.get('ordem', 0)))
        audios_ordenados = sorted(audios, key=lambda a: int(a.get('ordem', 0)))
        imagens_ordenadas = sorted(imagens, key=lambda i: int(i.get('ordem', 0)))

        for i, cena in enumerate(cenas):
            ordem = int(cena.get('ordem', i + 1) or (i + 1))
            audio_data = next((item for item in audios_ordenados if int(item.get('ordem', 0)) == ordem), None)
            img_data = next((item for item in imagens_ordenadas if int(item.get('ordem', 0)) == ordem), None)

            if audio_data is None or img_data is None:
                raise ValueError(f"Cena {ordem} sem áudio ou imagem correspondente para montagem.")

            audio_clip = AudioFileClip(str(audio_data['path']))
            duracao = audio_clip.duration

            img_clip = ImageClip(str(img_data['path'])).set_duration(duracao)

            if self.config['visual']['zoom_effect']:
                zoom_speed = self.config['visual']['zoom_speed']
                img_clip = img_clip.resize(lambda t: 1 + zoom_speed * t)

            texto_legenda = cena.get("texto_narrador")
            legenda = self._criar_legenda(texto_legenda, duracao, img_clip.size)

            scene_clip = img_clip.set_audio(audio_clip)
            if legenda:
                scene_clip = CompositeVideoClip([scene_clip, legenda]).set_duration(duracao)
            else:
                scene_clip = scene_clip.set_duration(duracao)

            clips.append(scene_clip)

        final_video = concatenate_videoclips(clips, method="compose")

        music_path = Path("assets/music/tech_ambient.mp3")
        if music_path.exists():
            bg_music = AudioFileClip(str(music_path))
            bg_music = bg_music.volumex(self.config['audio']['background_music_volume'])

            if bg_music.duration < final_video.duration:
                n_loops = int(final_video.duration / bg_music.duration) + 1
                bg_music = concatenate_audioclips([bg_music] * n_loops)

            bg_music = bg_music.subclip(0, final_video.duration)
            final_audio = CompositeAudioClip([final_video.audio, bg_music])
            final_video = final_video.set_audio(final_audio)
        
        # Salva vídeo
        filename = f"{roteiro['titulo'][:40].replace(' ', '_')}_{idioma}.mp4"
        filename = "".join(c for c in filename if c.isalnum() or c in ('_', '-', '.'))
        video_path = self.output_dir / filename
        
        final_video.write_videofile(
            str(video_path),
            fps=self.config['video']['fps'],
            codec='libx264',
            audio_codec='aac',
            bitrate=self.config['video']['bitrate'],
            preset='medium'
        )
        
        return video_path
    
    def _criar_legenda(self, texto, duracao, video_size):
        if not texto:
            return None

        txt_cfg = self.config["text"]

        legenda = TextClip(
            texto,
            fontsize=txt_cfg["subtitle_size"],
            color=txt_cfg["color"],
            font=txt_cfg["font"],
            method="caption",
            size=(int(video_size[0] * 0.9), None),
            align="center"
        ).set_duration(duracao)

        legenda = legenda.set_position(("center", "bottom"))
        return legenda


    def _aplicar_glitch(self, clip):
        # Efeito glitch simples
        def glitch_effect(get_frame, t):
            frame = get_frame(t)
            if np.random.random() > 0.9:  # 10% chance de glitch
                # Desloca canais RGB
                r, g, b = frame[:,:,0], frame[:,:,1], frame[:,:,2]
                shift = np.random.randint(-10, 10)
                frame[:,:,0] = np.roll(r, shift, axis=1)
                frame[:,:,2] = np.roll(b, -shift, axis=1)
            return frame
        
        return clip.fl(glitch_effect, apply_to=['mask'])
