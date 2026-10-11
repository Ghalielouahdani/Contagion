export function money(value: string | number | null | undefined) {
  if (value === null || value === undefined) return "n/a";
  const number = Number(value);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: Math.abs(number) >= 1000000 ? "compact" : "standard",
    maximumFractionDigits: Math.abs(number) >= 1000000 ? 2 : 0,
  }).format(number);
}

export function percent(value: string | number | null | undefined, digits = 1) {
  if (value === null || value === undefined) return "n/a";
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

export function signedPercent(value: number) {
  return `${value > 0 ? "+" : "-"}${Math.abs(value).toFixed(0)}%`;
}

export function compactId(id: string) {
  return id.replace("position:", "").replace(/_/g, " ");
}

export function labelize(value: string) {
  return value.replace(/_/g, " ");
}

/** A loss figure where a negative value is a gain (carry scenarios): "$6,482" or "gain $67,270". */
export function lossOrGain(value: string | number | null | undefined) {
  if (value === null || value === undefined) return "n/a";
  const number = Number(value);
  return number < 0 ? `gain ${money(-number)}` : money(number);
}

/** "lose $6,482" / "gain $67,270" (verb form), or "losing $6,482" / "gaining $67,270" with gerund. */
export function loseOrGain(value: string | number, gerund = false) {
  const number = Number(value);
  const verb = number < 0 ? (gerund ? "gaining" : "gain") : gerund ? "losing" : "lose";
  return `${verb} ${money(Math.abs(number))}`;
}
