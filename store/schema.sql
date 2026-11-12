PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app (
  id   TEXT PRIMARY KEY,
  name TEXT
);

CREATE TABLE IF NOT EXISTS scene (
  id            TEXT PRIMARY KEY,
  app_id        TEXT REFERENCES app(id),
  name          TEXT,
  entry_config  TEXT,
  traffic_share REAL
);

CREATE TABLE IF NOT EXISTS graph (
  id   TEXT PRIMARY KEY,
  name TEXT
);

CREATE TABLE IF NOT EXISTS scene_graph (
  scene_id TEXT REFERENCES scene(id),
  graph_id TEXT REFERENCES graph(id),
  PRIMARY KEY (scene_id, graph_id)
);

CREATE TABLE IF NOT EXISTS change (
  id        TEXT PRIMARY KEY,
  commit_id TEXT,
  mr        TEXT,
  graph_ids TEXT,
  author    TEXT,
  ts        TEXT
);

CREATE TABLE IF NOT EXISTS task (
  id        TEXT PRIMARY KEY,
  scene_id  TEXT REFERENCES scene(id),
  graph_id  TEXT REFERENCES graph(id),
  change_id TEXT REFERENCES change(id),
  trigger   TEXT,
  status    TEXT,
  ts        TEXT
);

CREATE TABLE IF NOT EXISTS snapshot (
  task_id        TEXT PRIMARY KEY REFERENCES task(id),
  upstream_model TEXT,
  entry_config   TEXT,
  traffic_share  REAL
);

CREATE TABLE IF NOT EXISTS report (
  task_id   TEXT PRIMARY KEY REFERENCES task(id),
  diff_rate REAL,
  p99       REAL,
  avg       REAL,
  verdict   TEXT,
  reasons   TEXT
);

CREATE TABLE IF NOT EXISTS span (
  trace_id TEXT,
  task_id  TEXT,
  name     TEXT,
  start_ms INTEGER,
  end_ms   INTEGER,
  status   TEXT,
  attrs    TEXT
);

-- 执行轮次：失败/超时的数据不覆盖，用 attempt 链表达重试关系
CREATE TABLE IF NOT EXISTS attempt (
  id             TEXT PRIMARY KEY,
  scene_id       TEXT,
  task_id        TEXT,
  round          INTEGER,
  status         TEXT,      -- running / completed / failed / timeout / aborted
  parent_attempt TEXT,      -- 重试指向上一轮
  created_at     TEXT,
  note           TEXT
);
