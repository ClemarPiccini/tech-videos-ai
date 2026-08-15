from elevenlabs import ElevenLabs

client = ElevenLabs()

voices = client.voices.get_all()

for v in voices.voices:
    print(f"Name: {v.name} | ID: {v.voice_id}")
