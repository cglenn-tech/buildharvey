export type StorylineEntry = {
  timestamp: string;
  text: string;
};

export type Screenshot = {
  id: string;
  timestamp: string;
  path: string;
  storageUrl: string;
  extractedText: string;
};

export type Episode = {
  id: string;
  title: string;
  started_at: string;
  ended_at: string;
  summary: string;
  storyline: StorylineEntry[];
  screenshots: Screenshot[];
  created_at: string;
};
