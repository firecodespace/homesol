import Anthropic from "@anthropic-ai/sdk";
import { AnthropicBedrockMantle } from "@anthropic-ai/bedrock-sdk";
import { zodOutputFormat } from "@anthropic-ai/sdk/helpers/zod";
import { Detection, DetectRequest } from "@/lib/detect/schema";

const MODEL = process.env.BEDROCK_MODEL_ID ?? "anthropic.claude-opus-5-5";

const SYSTEM = `You survey rooftops in India for solar panel installation from satellite images.

You are given a square, north-up satellite image. One roof is outlined in yellow: that is the roof where panels will go. Your job is to find everything that could cast a shadow onto that roof, so a shading calculation can account for it.

Report two kinds of objects:
- Things standing on the outlined roof: stair rooms (mumty), water tanks, lift rooms, parapet-height structures, sheds, existing equipment.
- Things next to it that rise above it: taller neighbouring buildings and trees. Skip neighbours that are clearly lower than the outlined roof, and skip anything more than about 30 m away unless it is a tall tower.

For each object give its footprint as it sits on the surface, not including its shadow. Satellite images lean slightly, so a tall building shows one or two of its walls; trace the roofline shifted back to where the base would be if you can tell, otherwise trace the roof.

Shadows are the best evidence of height. When an object's shadow is clearly visible from base to tip, report the foot of the corner casting it and the tip of that corner's shadow, both on the surface the shadow falls on. If the shadow is hidden, merges with another, or falls across surfaces at different levels, give null instead: a wrong shadow is worse than none.

Do not report the outlined roof itself, flat markings, stains, vehicles, or shadows as objects. If nothing would shade the roof, return an empty list.`;

export async function POST(request: Request) {
  const body = DetectRequest.safeParse(await request.json().catch(() => null));
  if (!body.success) return Response.json({ error: "Invalid request." }, { status: 400 });
  const { image, size, metresPerPixel, shadowBearing } = body.data;

  const context = [
    `The image is ${size} × ${size} pixels and each pixel covers about ${metresPerPixel.toFixed(2)} m.`,
    "Give coordinates in pixels with x to the right and y downwards from the top-left corner.",
    shadowBearing === null
      ? ""
      : `From the image date, shadows should point towards compass bearing ${Math.round(shadowBearing)}° (0° is up, 90° is right).`,
  ].join(" ");

  try {
    const client = new AnthropicBedrockMantle();
    const response = await client.messages.parse({
      model: MODEL,
      max_tokens: 16000,
      system: SYSTEM,
      messages: [
        {
          role: "user",
          content: [
            { type: "image", source: { type: "base64", media_type: "image/jpeg", data: image } },
            { type: "text", text: context },
          ],
        },
      ],
      output_config: { format: zodOutputFormat(Detection) },
    });

    if (response.stop_reason === "refusal") {
      return Response.json({ error: "The model declined to analyse this image." }, { status: 502 });
    }
    if (!response.parsed_output) {
      return Response.json({ error: "The model's answer could not be read. Try again." }, { status: 502 });
    }
    return Response.json(response.parsed_output);
  } catch (error) {
    if (error instanceof Anthropic.AuthenticationError || error instanceof Anthropic.PermissionDeniedError) {
      return Response.json({ error: `Bedrock refused the request: ${error.message}` }, { status: 502 });
    }
    if (error instanceof Anthropic.RateLimitError) {
      return Response.json({ error: "The model is busy. Try again in a minute." }, { status: 429 });
    }
    if (error instanceof Anthropic.APIError) {
      return Response.json({ error: `Model error (${error.status ?? "network"}): ${error.message}` }, { status: 502 });
    }
    throw error;
  }
}
