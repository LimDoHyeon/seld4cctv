from pathlib import Path


class OneShotSoundPlayer:
    def __init__(self, sound_path):
        self.sound_path = Path(sound_path)
        self._context = None
        self._sound_data = None
        self._voices = []
        self._carb_audio = None
        self._warned = False

    def load(self):
        if self._context is not None and self._sound_data is not None:
            return True
        if not self.sound_path.exists():
            self._warn_once(f"sound file not found: {self.sound_path}")
            return False

        try:
            carb_audio = self._import_carb_audio()
            playback = carb_audio.acquire_playback_interface()
            data = carb_audio.acquire_data_interface()
            self._context = playback.create_context()
            if self._context is None:
                raise RuntimeError("failed to create audio playback context")
            self._sound_data = data.create_sound_from_file(str(self.sound_path))
            if self._sound_data is None:
                raise RuntimeError(f"failed to load sound: {self.sound_path}")
            self._carb_audio = carb_audio
            return True
        except Exception as exc:
            self._context = None
            self._sound_data = None
            self._warn_once(f"audio unavailable: {exc}")
            return False

    def play(self):
        if not self.load():
            return False

        try:
            voice = self._context.play_sound(self._sound_data)
            if voice is not None:
                self._voices.append(voice)
            return voice is not None
        except Exception as exc:
            self._warn_once(f"sound playback failed: {exc}")
            return False

    def update(self):
        active = []
        for voice in self._voices:
            try:
                if voice.is_playing():
                    active.append(voice)
            except Exception:
                pass
        self._voices = active

    def stop(self):
        for voice in self._voices:
            for method_name in ("stop", "stop_sound"):
                method = getattr(voice, method_name, None)
                if not callable(method):
                    continue
                try:
                    method()
                    break
                except Exception:
                    pass
        self._voices = []
        self._sound_data = None
        self._context = None

    def _import_carb_audio(self):
        try:
            import carb.audio

            return carb.audio
        except Exception:
            import omni.kit.app

            manager = omni.kit.app.get_app().get_extension_manager()
            manager.set_extension_enabled_immediate("carb.audio", True)
            import carb.audio

            return carb.audio

    def _warn_once(self, message):
        if self._warned:
            return
        self._warned = True
        print(f"[cctv_sim] {message}")
