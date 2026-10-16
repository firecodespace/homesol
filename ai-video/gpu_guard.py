"""Keeps a laptop GPU in a comfortable range while the videos render.

Two profiles:
  balanced  (default) uses the GPU properly but pauses when it gets hot and rests between chunks.
  cool      for thin laptops or warm rooms: lower temperature limit, longer rests, and a short
            break after every denoising step so the average load stays low.

The watchdog reads the GPU temperature through NVIDIA's own management library (nvidia-ml-py).
If the GPU reaches the pause temperature it stops work until it has cooled to the resume temperature.
"""

import os
import time

PROFILES = {
    "balanced": {
        "pause_at_c": 83,  # stop and wait when the GPU reaches this
        "resume_at_c": 74,  # carry on once it has cooled to this
        "step_rest_s": 0.0,  # break after each denoising step
        "chunk_rest_s": 20,  # break after each 5-second chunk
        "vram_fraction": 0.85,  # share of video memory this program may take
        "upscale_tile": 384,
    },
    "cool": {
        "pause_at_c": 76,
        "resume_at_c": 66,
        "step_rest_s": 1.5,
        "chunk_rest_s": 60,
        "vram_fraction": 0.75,
        "upscale_tile": 256,
    },
}

# Below this much video memory the model is streamed layer by layer (slower, but fits 6 GB cards).
SEQUENTIAL_OFFLOAD_BELOW_GB = 7.5


class GpuGuard:
    def __init__(self, profile="balanced"):
        if profile not in PROFILES:
            raise SystemExit(f"Unknown profile '{profile}'. Use one of: {', '.join(PROFILES)}")
        self.name = profile
        self.p = PROFILES[profile]
        self._nvml = None
        self._handle = None
        try:
            import pynvml

            pynvml.nvmlInit()
            self._nvml = pynvml
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception:
            pass  # no NVIDIA driver or library; temperatures are then not watched

    # --- readings -------------------------------------------------------------------------

    def temperature(self):
        if not self._handle:
            return None
        try:
            return self._nvml.nvmlDeviceGetTemperature(self._handle, self._nvml.NVML_TEMPERATURE_GPU)
        except Exception:
            return None

    def describe(self):
        import torch

        if not torch.cuda.is_available():
            return "No CUDA GPU found: generation would run on the CPU and take days. Check the NVIDIA driver and PyTorch install."
        props = torch.cuda.get_device_properties(0)
        temp = self.temperature()
        temp_text = f"{temp} °C" if temp is not None else "temperature not readable (install nvidia-ml-py)"
        return (
            f"{props.name}, {props.total_memory / 2**30:.1f} GB video memory, {temp_text}. "
            f"Profile '{self.name}': pauses at {self.p['pause_at_c']} °C, resumes at {self.p['resume_at_c']} °C, "
            f"uses at most {int(self.p['vram_fraction'] * 100)}% of video memory."
        )

    def vram_gb(self):
        import torch

        return torch.cuda.get_device_properties(0).total_memory / 2**30 if torch.cuda.is_available() else 0.0

    # --- setup ----------------------------------------------------------------------------

    def setup_torch(self):
        import torch

        # Leave CPU cores free so the laptop stays usable.
        torch.set_num_threads(max(1, (os.cpu_count() or 4) // 2))
        if torch.cuda.is_available():
            torch.cuda.set_per_process_memory_fraction(self.p["vram_fraction"], 0)
            torch.backends.cuda.matmul.allow_tf32 = True

    def place_pipeline(self, pipe):
        """Keep only the part of the model that is working on the GPU."""
        if self.vram_gb() < SEQUENTIAL_OFFLOAD_BELOW_GB:
            print("  Less than 8 GB of video memory: streaming the model layer by layer (slower).")
            pipe.enable_sequential_cpu_offload()
        else:
            pipe.enable_model_cpu_offload()

    # --- pacing ---------------------------------------------------------------------------

    def wait_if_hot(self):
        temp = self.temperature()
        if temp is None or temp < self.p["pause_at_c"]:
            return
        print(f"\n  GPU at {temp} °C: pausing until it cools to {self.p['resume_at_c']} °C ...", flush=True)
        while True:
            time.sleep(5)
            temp = self.temperature()
            if temp is None or temp <= self.p["resume_at_c"]:
                print(f"  GPU at {temp} °C: carrying on.", flush=True)
                return

    def step_callback(self, pipe, step, timestep, callback_kwargs):
        """Called by diffusers after every denoising step."""
        self.wait_if_hot()
        if self.p["step_rest_s"]:
            time.sleep(self.p["step_rest_s"])
        return callback_kwargs

    def rest_between_chunks(self):
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        if self.p["chunk_rest_s"]:
            print(f"  Resting the GPU for {self.p['chunk_rest_s']} s ...", flush=True)
            time.sleep(self.p["chunk_rest_s"])
        self.wait_if_hot()
