import React, { useState, useRef, useEffect } from 'react';
import {
  Terminal,
  Copy,
  Check,
  Trash2,
  Filter,
  Maximize2,
  Minimize2
} from 'lucide-react';
import type { LogEntry, LogLevel } from '../../types';

interface OutputLogsProps {
  logs: LogEntry[];
  onClearLogs: () => void;
}

export const OutputLogs: React.FC<OutputLogsProps> = ({
  logs,
  onClearLogs
}) => {
  const [filterLevel, setFilterLevel] = useState<string>('all');
  const [copied, setCopied] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [isExpanded, setIsExpanded] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  const filteredLogs = logs.filter((log) => {
    if (filterLevel === 'all') return true;
    return log.level === filterLevel;
  });

  const handleCopyLogs = () => {
    const text = filteredLogs
      .map((l) => `[${l.timestamp}] [${l.source}] ${l.message}`)
      .join('\n');
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const getLogBadgeClass = (level: LogLevel) => {
    switch (level) {
      case 'success':
        return 'badge-success';
      case 'error':
        return 'badge-error';
      case 'warn':
        return 'badge-warn';
      case 'agent':
        return 'badge-agent';
      case 'system':
        return 'badge-system';
      case 'info':
      default:
        return 'badge-info';
    }
  };

  return (
    <div className={`terminal-panel-card ${isExpanded ? 'expanded' : ''}`}>
      {/* Terminal Top Bar */}
      <div className="terminal-header">
        <div className="terminal-title-group">
          <div className="terminal-window-dots">
            <span className="window-dot red" />
            <span className="window-dot yellow" />
            <span className="window-dot green" />
          </div>
          <div className="terminal-name">
            <Terminal size={14} className="term-icon" />
            <span>Output Stream</span>
            <span className="demo-stream-badge">DEMO LOGS</span>
          </div>
        </div>

        {/* Action controls */}
        <div className="terminal-controls">
          {/* Filter Dropdown */}
          <div className="log-filter-box">
            <Filter size={12} className="filter-icon" />
            <select
              className="log-filter-select"
              value={filterLevel}
              onChange={(e) => setFilterLevel(e.target.value)}
              aria-label="Log Seviyesi Filtrele"
            >
              <option value="all">Tüm Seviyeler ({logs.length})</option>
              <option value="system">System</option>
              <option value="agent">Agent</option>
              <option value="info">Info</option>
              <option value="success">Success</option>
              <option value="warn">Warn / Error</option>
            </select>
          </div>

          {/* Auto scroll toggle */}
          <button
            className={`term-tool-btn ${autoScroll ? 'active' : ''}`}
            onClick={() => setAutoScroll(!autoScroll)}
            title={autoScroll ? 'Otomatik kaydırma açık' : 'Otomatik kaydırma kapalı'}
          >
            <span>Auto-scroll</span>
          </button>

          {/* Copy Logs */}
          <button
            className="term-tool-btn"
            onClick={handleCopyLogs}
            title="Logları panoya kopyala"
          >
            {copied ? <Check size={13} className="text-green" /> : <Copy size={13} />}
            <span>{copied ? 'Kopyalandı' : 'Kopyala'}</span>
          </button>

          {/* Clear Logs */}
          <button
            className="term-tool-btn"
            onClick={onClearLogs}
            title="Log akışını temizle"
          >
            <Trash2 size={13} />
            <span>Temizle</span>
          </button>

          {/* Expand / Minimize */}
          <button
            className="term-tool-btn icon-only"
            onClick={() => setIsExpanded(!isExpanded)}
            title={isExpanded ? 'Küçült' : 'Genişlet'}
            aria-label={isExpanded ? 'Küçült' : 'Genişlet'}
          >
            {isExpanded ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
          </button>
        </div>
      </div>

      {/* Terminal Body / Console Output */}
      <div className="terminal-console-body" ref={scrollRef}>
        <div className="terminal-watermark">
          [DEMO MODE: Gerçek zamanlı terminal simülasyonu • Backend bağlantısız demo akışı]
        </div>

        {filteredLogs.length === 0 ? (
          <div className="terminal-empty-state">
            <span>Seçili filtreye uygun log kaydı bulunamadı.</span>
          </div>
        ) : (
          filteredLogs.map((log) => (
            <div key={log.id} className="terminal-line-row">
              <span className="term-col-time">{log.timestamp}</span>
              <span className={`term-col-source ${getLogBadgeClass(log.level)}`}>
                [{log.source}]
              </span>
              <span className={`term-col-msg msg-${log.level}`}>
                {log.message}
              </span>
            </div>
          ))
        )}
      </div>

      {/* Terminal Footer Indicator */}
      <div className="terminal-footer">
        <div className="term-footer-left">
          <span className="pulse-dot green small" />
          <span className="term-footer-status">Stream Active • Synthetic Output</span>
        </div>
        <span className="term-footer-count">Toplam {filteredLogs.length} satır</span>
      </div>
    </div>
  );
};
