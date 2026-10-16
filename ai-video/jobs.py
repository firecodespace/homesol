"""What each video is: which photo, which part of the reference clip, and what the prompt says.

Edit the prompts here. Times are seconds in inputs/reference.mp4 (the screen recording).
"""

REFERENCE_VIDEO = "inputs/reference.mp4"

# The Instagram clip sits inside a phone screen recording. Its box is found automatically;
# set this to (x, y, w, h) only if the detection picks the wrong area.
REFERENCE_CROP = None

# The app's like/comment/share icons cover the right side of the clip. From this fraction
# of the width onwards the picture is regenerated, so the icons disappear.
OVERLAY_STRIP_FROM = 0.82

# The racetrack clip without its first second (a different reel) and its last second
# (the pause icon).
FULL_CLIP = [(1.0, 23.4)]

SCENE = (
    "on an empty motor-racing circuit at golden hour, the low sun setting behind the grandstands, "
    "warm orange sky, red and white kerbs, green grass, a silver Bugatti Chiron hypercar parked on "
    "the asphalt behind, handheld phone video, natural light, photorealistic, sharp detail"
)

NEGATIVE = (
    "blurry, low quality, jpeg artifacts, deformed face, distorted face, extra fingers, fused fingers, "
    "bad hands, extra limbs, watermark, text, subtitles, logo, icons, cartoon, painting, overexposed, "
    "static frame, flicker"
)

JOBS = {
    # The person from the photo in the racetrack clip, with a cap and sunglasses.
    "me_sunglasses": {
        "kind": "replace",
        "photo": "inputs/me.jpg",
        "photo_crop": "head",
        "segments": FULL_CLIP,
        "prompt": (
            "A young man with thick black curly hair and a light trimmed beard, wearing a black "
            "baseball cap and dark wraparound sunglasses and a plain black hoodie, talking to the "
            "camera and now and then holding up red and blue UNO cards, " + SCENE
        ),
        "negative": NEGATIVE + ", eyeglasses with clear lenses",
        "audio": "reference",
    },
    # The same, with a cap but no sunglasses: his own clear-framed glasses, eyes visible.
    # To show him without any glasses, change the prompt and move "eyeglasses" to the negative.
    "me_no_sunglasses": {
        "kind": "replace",
        "photo": "inputs/me.jpg",
        "photo_crop": "head",
        "segments": FULL_CLIP,
        "prompt": (
            "A young man with thick black curly hair and a light trimmed beard, wearing a black "
            "baseball cap, thin clear-framed eyeglasses with his eyes visible, and a plain black "
            "hoodie, talking to the camera and now and then holding up red and blue UNO cards, " + SCENE
        ),
        "negative": NEGATIVE + ", sunglasses, dark lenses, tinted glasses",
        "audio": "reference",
    },
    # Jason Duval takes the man's place in the two card-flip moments of the clip.
    "jason_cards": {
        "kind": "replace",
        "photo": "inputs/jason.jpg",
        "photo_crop": "upper_body",
        "segments": [(1.0, 5.7), (16.0, 19.0)],
        "prompt": (
            "Jason Duval from Grand Theft Auto VI, a rugged man in his thirties with short dark hair "
            "and stubble, ex-army build, wearing a black cap and a dark hoodie, confidently flipping "
            "playing cards between his fingers and showing them to the camera, smirking, " + SCENE
        ),
        "negative": NEGATIVE,
        "audio": "reference",
    },
    # Lucia Caminos posing like a model in front of the car, on the clip's empty-car shot.
    "lucia_car": {
        "kind": "place",
        "photo": "inputs/lucia.jpg",
        "photo_crop": "full",
        "background_at": 14.3,  # the moment the clip shows the car with nobody in front
        "seconds": 5.0,
        "push_in": 1.10,  # slow camera push-in over the shot
        # Where she stands, as fractions of the frame: left, top, right, bottom.
        "place_box": (0.20, 0.04, 0.56, 1.0),
        "prompt": (
            "Lucia Caminos from Grand Theft Auto VI, a confident Latina woman with long dark hair and "
            "gold hoop earrings, standing in front of the silver Bugatti and posing like a fashion "
            "model, one hand on her hip, slowly turning her head to look into the camera, hair moving "
            "in the breeze, " + SCENE
        ),
        "negative": NEGATIVE + ", man, second person",
        # The original track carries on from where Jason's part ends.
        "audio": "reference",
        "audio_segments": [(19.0, 24.0)],
    },
}

# Finished videos made by joining jobs end to end.
COMBINED = {
    "gta6_jason_lucia": ["jason_cards", "lucia_car"],
}
