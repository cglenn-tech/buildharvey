export type KeyObservation = {
  timestamp: string; // HH:MM
  text: string;      // "Reviewed appraisal report"
};

export type Episode = {
  id: string;
  case_name: string;
  started_at: string;
  ended_at: string;
  duration_minutes: number;
  key_observations: KeyObservation[];
  created_at: string;
  is_reportable?: boolean;
};

// Season is a client-side grouping — never stored in the backend.
export type DayGroup = {
  label: string;  // "Monday"
  date: string;   // "2024-01-08"
  episodes: Episode[];
};

export type Season = {
  weekStart: string;  // "2024-01-08"
  weekEnd: string;    // "2024-01-14"
  label: string;      // "This week" | "Last week" | "Week of Jan 8"
  days: DayGroup[];
};
