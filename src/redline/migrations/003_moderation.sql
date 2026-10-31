CREATE TABLE IF NOT EXISTS moderation_actions (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 target_id TEXT NOT NULL,
 actor_id TEXT NOT NULL,
 action TEXT NOT NULL,
 reason TEXT NOT NULL,
 created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS moderation_target ON moderation_actions(target_id, id);
