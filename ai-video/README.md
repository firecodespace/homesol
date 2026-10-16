# AI racetrack videos in 4K, made from code

Four videos made from the racetrack clip (a man in a cap at a sunset circuit, flipping UNO cards, a silver Bugatti behind him):

| Output | What it shows |
|---|---|
| `output/me_sunglasses_4k.mp4` | The person from your photo in his place: black cap, dark sunglasses, black hoodie |
| `output/me_no_sunglasses_4k.mp4` | The same, with the cap but no sunglasses (his own clear glasses) |
| `output/jason_cards_4k.mp4` | Jason Duval (GTA VI) flipping and showing the cards |
| `output/lucia_car_4k.mp4` | Lucia Caminos (GTA VI) posing like a model in front of the car |
| `output/gta6_jason_lucia_4k.mp4` | Jason's part, then Lucia's, joined |

Each video is 3840x2160 at 30 fps with the **original clip's own sound**. The voice is cleaned up: rumble cut, hiss reduced, speech lifted and the loudness levelled. The track, sky, light and car come from the original clip, so the setting looks the same.

## How it works

1. **Prep.** The clip is cut out of the phone screen recording. In every frame the person is found and their body, hand and face pose is drawn as a skeleton. Your photo is cut out onto white.
2. **Generate.** [Wan 2.1 VACE 1.3B](https://huggingface.co/Wan-AI/Wan2.1-VACE-1.3B-diffusers), an open video model, redraws only the person's area of each frame. It follows the original pose and takes the look from the photo and the prompt. It works in 5-second chunks, and each chunk continues from the last.
3. **Finish.** The 16 fps frames are smoothed to 30 fps, upscaled 4x with Real-ESRGAN, sized to 3840x2160, and encoded with the cleaned-up sound.

The model draws at 848x480, and Real-ESRGAN adds the 4K detail. No laptop GPU can draw native 4K video.

## Your laptop's GPU is protected

`gpu_guard.py` watches the GPU temperature after every step of the model:

| Profile | Pauses at | Resumes at | Rest between chunks | Use |
|---|---|---|---|---|
| `balanced` (default) | 83 °C | 74 °C | 20 s | Uses the GPU properly, never runs flat out when hot |
| `cool` (`--profile cool`) | 76 °C | 66 °C | 60 s, plus 1.5 s after every step | Thin laptops, warm rooms; about 1.5–2x slower |

It also:
- caps video memory use at 85% (75% on `cool`);
- keeps only the working part of the model on the GPU;
- tiles the image work, and streams the model layer by layer on cards under 8 GB;
- leaves half your CPU cores free.

The 11 GB text encoder runs once, its output is saved, and it is unloaded before the video model starts.

Stop at any time with **Ctrl+C**. Run the same command again and it carries on from the last finished frame.

## Setup (once)

You need an NVIDIA GPU with 6 GB or more of video memory (8 GB is better), 16 GB of RAM and about 25 GB of free disk.

**1. Install the basics**

- An up-to-date NVIDIA driver
- Python 3.11 from python.org (tick "Add to PATH")
- ffmpeg. On Windows: `winget install Gyan.FFmpeg`, then open a new terminal. On Linux: `sudo apt install ffmpeg`.

**2. Install the Python packages** (in this folder)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate        Linux:  source .venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
```

**3. Put your files in `inputs/`** (see `inputs/README.md`)

- `reference.mp4`: the racetrack video
- `me.jpg`: the person's photo
- `jason.jpg` and `lucia.jpg`: the official character art from Rockstar's [GTA VI people page](https://www.rockstargames.com/VI/people). Right-click each portrait, save it, and rename it.

## Make the videos

```bash
python run.py check                    # GPU, temperature, ffmpeg and input files
python run.py preview me_sunglasses    # 5-second 1080p test (about 10–20 min): check the face and motion
python run.py all                      # all four videos and the joined GTA video, in 4K
```

You can also run one step or one job, e.g. `python run.py generate jason_cards` or `python run.py finish all --upscaler esrgan-soft`.

**Time.** These are rough figures for an RTX 4060 laptop GPU on `balanced`:
- about 10–15 minutes per 5-second chunk;
- each of your 22-second videos is 5 chunks, about 1–1.5 hours;
- Jason is 2 chunks and Lucia is 1;
- `all` takes about 3–4 hours.

Leave it plugged in and stop the laptop from sleeping. Set Windows power mode to Balanced, not Best performance, and raise the back of the laptop for airflow.

## Changing things

Everything about the videos is in `jobs.py`: the prompts, which seconds of the clip are used, where Lucia stands, and the sound for each part.

- **Face doesn't look enough like the photo:** use a sharper, front-facing photo with good light.
- **No glasses at all in the no-sunglasses version:** change its prompt to "no glasses" and add "eyeglasses" to its `negative`.
- **Skin looks plastic after upscaling:** finish with `--upscaler esrgan-soft`.
- **Change the voice cleanup:** edit `VOICE_CLEANUP` in `prep.py`, then run `prep` again.

## Please note

- Only use a real person's photo with that person's permission.
- Jason, Lucia and their artwork belong to Rockstar Games. These videos are fan content for personal use; don't sell them or present them as official.
- The racetrack clip and its soundtrack belong to their creators. Keep the results personal, or credit the original creator if you post them.
