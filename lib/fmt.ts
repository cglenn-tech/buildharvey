/**
 * Shared 12-hour time formatters.
 * All timestamps in the BuildHarvey UI use these functions for consistency.
 */

export function fmt12Time(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

export function fmt12Range(start: string, end: string): string {
  return `${fmt12Time(start)} – ${fmt12Time(end)}`;
}

export function fmt12Date(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}
