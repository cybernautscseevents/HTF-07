/**
 * Currency formatting utilities for AEGIS-Flow.
 * 
 * Rules:
 * - Domain layer preserves pure integer minor units (paise for INR).
 * - Floating point conversion occurs solely at presentation layer.
 * - Handles undefined, null, and 0 gracefully.
 */

export function minorUnitsToMajor(minorUnits: number | null | undefined): number {
  if (minorUnits == null || isNaN(minorUnits)) return 0;
  return minorUnits / 100;
}

export function formatMinorUnits(
  minorUnits: number | null | undefined,
  currency: string = "INR"
): string {
  if (minorUnits == null || isNaN(minorUnits)) {
    return currency === "INR" ? "₹0.00" : `0.00 ${currency}`;
  }

  const major = minorUnitsToMajor(minorUnits);

  try {
    const formatter = new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: currency.toUpperCase(),
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    return formatter.format(major);
  } catch {
    // Fallback if locale or currency unsupported
    const symbol = currency.toUpperCase() === "INR" ? "₹" : `${currency} `;
    return `${symbol}${major.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }
}

export function formatCompactINR(minorUnits: number | null | undefined): string {
  if (minorUnits == null || isNaN(minorUnits)) return "₹0";
  const major = minorUnitsToMajor(minorUnits);
  const abs = Math.abs(major);
  const sign = major < 0 ? "-" : "";

  if (abs >= 10_000_000) {
    return `${sign}₹${(abs / 10_000_000).toFixed(2)} Cr`;
  }
  if (abs >= 100_000) {
    return `${sign}₹${(abs / 100_000).toFixed(2)} L`;
  }
  if (abs >= 1_000) {
    return `${sign}₹${(abs / 1_000).toFixed(1)} K`;
  }
  return `${sign}₹${abs.toFixed(2)}`;
}

export function formatPaise(minorUnits: number | null | undefined): string {
  if (minorUnits == null || isNaN(minorUnits)) return "0 paise";
  return `${minorUnits.toLocaleString("en-IN")} paise`;
}

/**
 * Formats recovery efficiency values cleanly for user-facing displays.
 * e.g., "5.333333333333333" -> "5.3×", "Infinity" -> "∞ (Zero collateral)"
 */
export function formatEfficiency(efficiency: string | number | null | undefined): string {
  if (efficiency == null) return "N/A";
  const str = String(efficiency).trim();
  if (str === "Infinity" || str === "inf") {
    return "∞ (Zero collateral)";
  }
  const num = parseFloat(str);
  if (isNaN(num)) return str;
  return `${num.toFixed(1)}×`;
}

