import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";

type SearchResult = {
  id: string;
  title: string;
  author?: string;
  description?: string;
  bot?: string;
  size_bytes?: number;
};

type JobStatus = "queued" | "started" | "finished" | "failed";

type JobInfo = {
  id: string;
  status: JobStatus;
  enqueued_at?: string;
  started_at?: string;
  ended_at?: string;
  error?: string;
  result_path?: string;
};

type ConfigData = {
  download_dir: string;
  library_dir: string;
  temp_dir: string;
  max_download_bytes?: number | null;
  allowed_bots: string[];
  irc_server?: string | null;
  irc_port?: number | null;
  irc_ssl?: boolean | null;
  irc_ssl_verify?: boolean | null;
  irc_channel?: string | null;
  irc_nick?: string | null;
  irc_realname?: string | null;
  theme: "light" | "dark";
};

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://localhost:8000",
});

function formatBytes(bytes?: number) {
  if (!bytes) return "unknown size";
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const value = bytes / 1024 ** i;
  return `${value.toFixed(1)} ${sizes[i]}`;
}

export default function App() {
  const [query, setQuery] = useState("");
  const [author, setAuthor] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [jobs, setJobs] = useState<Record<string, JobInfo>>({});
  const [view, setView] = useState<"search" | "config">("search");
  const [config, setConfig] = useState<ConfigData | null>(null);
  const [configSaving, setConfigSaving] = useState(false);
  const [allowedBots, setAllowedBots] = useState("");
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [ircLog, setIrcLog] = useState<string[]>([]);
  const [ircStatus, setIrcStatus] = useState<{ connected: boolean; error?: string | null }>({ connected: false, error: null });
  const [ircBusy, setIrcBusy] = useState(false);

  const pollJobs = useCallback(async () => {
    const jobIds = Object.keys(jobs);
    if (!jobIds.length) return;
    const updates: Record<string, JobInfo> = {};
    for (const id of jobIds) {
      try {
        const { data } = await api.get<JobInfo>(`/jobs/${id}`);
        updates[id] = data;
      } catch (err) {
        console.error("job poll failed", err);
      }
    }
    if (Object.keys(updates).length) {
      setJobs((prev) => ({ ...prev, ...updates }));
    }
  }, [jobs]);

  useEffect(() => {
    const t = setInterval(pollJobs, 2000);
    return () => clearInterval(t);
  }, [pollJobs]);

  useEffect(() => {
    api
      .get<ConfigData>("/config")
      .then(({ data }) => {
        setConfig(data);
        setAllowedBots(data.allowed_bots.join(", "));
        setTheme(data.theme);
      })
      .catch((err) => console.error("config load failed", err));
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    let timer: number | undefined;
    const fetchLog = async () => {
      if (view !== "log") return;
      try {
        const { data } = await api.get<{ lines: string[] }>("/irc-log");
        setIrcLog(data.lines.reverse());
      } catch (err) {
        console.error("log fetch failed", err);
      }
    };
    if (view === "log") {
      fetchLog();
      timer = window.setInterval(fetchLog, 2000);
    }
    return () => {
      if (timer) window.clearInterval(timer);
    };
  }, [view]);

  useEffect(() => {
    if (view !== "log") return;
    const poll = async () => {
      try {
        const { data } = await api.get<{ connected: boolean; error?: string }>("/irc/status");
        setIrcStatus({ connected: data.connected, error: data.error || null });
      } catch (err) {
        console.error("status fetch failed", err);
      }
    };
    poll();
    const t = setInterval(poll, 2000);
    return () => clearInterval(t);
  }, [view]);

  const connectIrc = async () => {
    setIrcBusy(true);
    try {
      await api.post("/irc/connect");
    } catch (err) {
      console.error(err);
    } finally {
      setIrcBusy(false);
    }
  };

  const disconnectIrc = async () => {
    setIrcBusy(true);
    try {
      await api.post("/irc/disconnect");
    } catch (err) {
      console.error(err);
    } finally {
      setIrcBusy(false);
    }
  };

  const clearLog = async () => {
    try {
      await api.post("/irc-log/clear");
      setIrcLog([]);
    } catch (err) {
      console.error(err);
    }
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    setSearching(true);
    try {
      const { data } = await api.post<{ results: SearchResult[] }>("/search", {
        query,
        author: author || undefined,
      });
      setResults(data.results);
    } catch (err) {
      console.error(err);
    } finally {
      setSearching(false);
    }
  };

  const startDownload = async (result: SearchResult) => {
    try {
      const { data } = await api.post<{ job_id: string }>("/download", {
        result_id: result.id,
        bot: result.bot,
      });
      setJobs((prev) => ({ ...prev, [data.job_id]: { id: data.job_id, status: "queued" } }));
    } catch (err) {
      console.error(err);
    }
  };

  const activeJobs = useMemo(() => Object.values(jobs).sort((a, b) => (b.enqueued_at || "").localeCompare(a.enqueued_at || "")), [jobs]);

  const saveConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!config) return;
    setConfigSaving(true);
    try {
      const payload: ConfigData = {
        ...config,
        allowed_bots: allowedBots
          .split(",")
          .map((b) => b.trim())
          .filter(Boolean),
        theme,
      };
      const { data } = await api.post<ConfigData>("/config", payload);
      setConfig(data);
      setAllowedBots(data.allowed_bots.join(", "));
      setTheme(data.theme);
    } catch (err) {
      console.error(err);
    } finally {
      setConfigSaving(false);
    }
  };

  return (
    <div className="page">
      <div className="topbar">
        <div className="title">
          <h1>lircbrary</h1>
          <div className="pill">alpha</div>
        </div>
        <div className="topbar-actions">
          <button className="ghost" onClick={() => setTheme(theme === "light" ? "dark" : "light")}>
            {theme === "light" ? "Dark mode" : "Light mode"}
          </button>
        </div>
      </div>

      <div className="tabs">
        <button className={view === "search" ? "tab active" : "tab"} onClick={() => setView("search")}>
          Search
        </button>
        <button className={view === "config" ? "tab active" : "tab"} onClick={() => setView("config")}>
          Settings
        </button>
        <button className={view === "log" ? "tab active" : "tab"} onClick={() => setView("log")}>
          IRC Log
        </button>
      </div>

      {view === "search" && (
        <>
          <div className="card">
            <form className="form" onSubmit={handleSearch}>
              <div className="inputs">
                <label>
                  Title or keywords
                  <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. The Pragmatic Programmer" required />
                </label>
                <label>
                  Author (optional)
                  <input value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="e.g. Andrew Hunt" />
                </label>
              </div>
              <div>
                <button type="submit" disabled={searching}>
                  {searching ? "Searching..." : "Search channel"}
                </button>
              </div>
            </form>
          </div>

          <div className="card">
            <h3>Results</h3>
            <div className="results">
              {results.map((r) => (
                <div className="result-row" key={r.id}>
                  <div className="result-meta">
                    <div className="result-title">{r.title}</div>
                    <div className="result-desc">
                      {r.author && `${r.author} • `} {r.description || "No description"} • {formatBytes(r.size_bytes)}
                    </div>
                  </div>
                  <button onClick={() => startDownload(r)}>Request</button>
                </div>
              ))}
              {!results.length && <div className="result-desc">Run a search to see packs.</div>}
            </div>
          </div>

          <div className="card">
            <h3>Activity</h3>
            <div className="status-grid">
              {activeJobs.map((j) => (
                <div className="status-row" key={j.id}>
                  <div>
                    <strong>{j.status.toUpperCase()}</strong> {j.result_path && `→ ${j.result_path}`}
                  </div>
                  <div>{j.error ? j.error.split("\n")[0] : ""}</div>
                </div>
              ))}
              {!activeJobs.length && <div className="result-desc">No active jobs yet.</div>}
            </div>
          </div>
        </>
      )}

      {view === "config" && config && (
        <div className="card">
          <form className="form" onSubmit={saveConfig}>
            <div className="inputs">
              <label>
                Library folder
                <input value={config.library_dir} onChange={(e) => setConfig({ ...config, library_dir: e.target.value })} />
              </label>
              <label>
                Downloads folder
                <input value={config.download_dir} onChange={(e) => setConfig({ ...config, download_dir: e.target.value })} />
              </label>
              <label>
                Temp folder
                <input value={config.temp_dir} onChange={(e) => setConfig({ ...config, temp_dir: e.target.value })} />
              </label>
              <label>
                Max download bytes (optional)
                <input
                  type="number"
                  min={0}
                  value={config.max_download_bytes ?? ""}
                  onChange={(e) => setConfig({ ...config, max_download_bytes: e.target.value ? Number(e.target.value) : null })}
                />
              </label>
              <label>
                Allowed bots (comma separated)
                <input value={allowedBots} onChange={(e) => setAllowedBots(e.target.value)} placeholder="bot1, bot2" />
              </label>
              <label>
                IRC server
                <input value={config.irc_server || ""} onChange={(e) => setConfig({ ...config, irc_server: e.target.value })} />
              </label>
              <label>
                IRC port
                <input
                  type="number"
                  value={config.irc_port ?? ""}
                  onChange={(e) => setConfig({ ...config, irc_port: e.target.value ? Number(e.target.value) : null })}
                />
              </label>
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={config.irc_ssl ?? false}
                  onChange={(e) => setConfig({ ...config, irc_ssl: e.target.checked })}
                  style={{ width: "auto" }}
                />
                Use SSL/TLS (try port 6697)
              </label>
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={config.irc_ssl_verify ?? true}
                  onChange={(e) => setConfig({ ...config, irc_ssl_verify: e.target.checked })}
                  style={{ width: "auto" }}
                />
                Verify SSL certificates
              </label>
              <label>
                IRC channel
                <input value={config.irc_channel || ""} onChange={(e) => setConfig({ ...config, irc_channel: e.target.value })} />
              </label>
              <label>
                IRC nick
                <input value={config.irc_nick || ""} onChange={(e) => setConfig({ ...config, irc_nick: e.target.value })} />
              </label>
              <label>
                IRC realname
                <input value={config.irc_realname || ""} onChange={(e) => setConfig({ ...config, irc_realname: e.target.value })} />
              </label>
            </div>
            <div className="form-row">
              <div className="toggle">
                <span>Theme</span>
                <button type="button" className="ghost" onClick={() => setTheme(theme === "light" ? "dark" : "light")}>
                  {theme === "light" ? "Switch to dark" : "Switch to light"}
                </button>
              </div>
              <button type="submit" disabled={configSaving}>
                {configSaving ? "Saving..." : "Save settings"}
              </button>
            </div>
          </form>
        </div>
      )}

      {view === "log" && (
        <div className="card">
          <div className="log-header">
            <div>
              <h3>IRC Debug Log</h3>
              <div className="status-chip">{ircStatus.connected ? "Connected" : "Disconnected"}</div>
              {ircStatus.error && <div className="result-desc">{ircStatus.error}</div>}
            </div>
            <div className="topbar-actions">
              <button className="ghost" onClick={connectIrc} disabled={ircBusy}>
                Connect
              </button>
              <button className="ghost" onClick={disconnectIrc} disabled={ircBusy}>
                Disconnect
              </button>
              <button className="ghost" onClick={clearLog}>
                Clear log
              </button>
            </div>
          </div>
          <div className="log-box">
            {ircLog.map((line, idx) => (
              <div key={idx} className="log-line">
                {line}
              </div>
            ))}
            {!ircLog.length && <div className="result-desc">No log lines yet.</div>}
          </div>
        </div>
      )}
    </div>
  );
}
