import { Html5Audio } from "remotion";
import { assetById } from "../assets";

/** Level under the voice and the sfx. */
const VOLUME = 0.25;

// A template's background music (step 048a): a music loop from src/assets.ts under the whole
// video, so a Reel without a voice still has sound. "none" plays nothing.
export const MusicBed = ({ id }: { id: "music-overworld" | "music-cave" | "music-marimba" | "music-kalimba" | "none" }) =>
  id === "none" ? null : <Html5Audio src={assetById(id).src} loop volume={VOLUME} />;
