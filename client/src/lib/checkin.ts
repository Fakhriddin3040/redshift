export const SCALES = [
  ["sleep", "How well did you sleep?", "Poorly", "Very well"],
  ["mood", "Mood", "Low", "Good"],
  ["energy", "Energy", "Drained", "Full"],
] as const;

export const SYMPTOMS = [
  ["headache", "Headache"],
  ["congestion", "Nasal congestion"],
  ["back", "Back pain"],
  ["vision", "Blurred near vision"],
  ["nausea", "Nausea"],
  ["skin", "Skin irritation"],
] as const;

export const SYMPTOM_LABEL: Record<string, string> = Object.fromEntries(SYMPTOMS);
