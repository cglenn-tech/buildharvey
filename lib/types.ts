export type KeyObservation = {
  timestamp: string; // ISO string or HH:MM
  text: string;      // "Drafted motion to compel, Peterson v. Ortega"
  task_description?: string | null;  // specific task from analysis
};

export type Episode = {
  id: string;                                    // UUID-formatted TEXT for web; TEXT for desktop
  case_name: string;
  work_type: 'project' | 'administrative';
  issue_worked_on?: string | null;
  started_at: string;
  ended_at: string;
  duration_minutes: number;
  key_observations: KeyObservation[];
  created_at: string;
  is_reportable?: boolean;
  edited_at?: string | null;
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
