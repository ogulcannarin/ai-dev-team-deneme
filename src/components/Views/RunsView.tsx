import React from 'react';
import { History, GitBranch, ArrowUpRight } from 'lucide-react';
import type { TaskItem } from '../../types';

interface RunsViewProps {
  tasks: TaskItem[];
  onSelectRun?: (taskId: string) => void;
}

export const RunsView: React.FC<RunsViewProps> = ({ tasks, onSelectRun }) => {
  return (
    <div className="view-container">
      <div className="view-header">
        <div>
          <h2 className="view-title">Pipeline Execution Runs</h2>
          <p className="view-subtitle">
            Geçmiş ve devam eden otonom pipeline koşturmaları ve yürütme günlükleri
          </p>
        </div>
        <div className="view-badge-tag">
          <History size={14} />
          <span>{tasks.length} Total Runs • Demo</span>
        </div>
      </div>

      <div className="runs-table-card">
        <table className="runs-table">
          <thead>
            <tr>
              <th>Run ID / Başlık</th>
              <th>Durum</th>
              <th>Branch</th>
              <th>Öncelik</th>
              <th>Oluşturulma</th>
              <th>Görevli Agent'lar</th>
              <th>İşlem</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <tr key={task.id} className="run-table-row">
                <td>
                  <div className="run-id-cell">
                    <span className="run-id-tag">{task.id}</span>
                    <span className="run-title-text">{task.title}</span>
                  </div>
                </td>
                <td>
                  <span
                    className={`status-pill ${
                      task.status === 'in_progress'
                        ? 'running'
                        : task.status === 'completed'
                        ? 'completed'
                        : 'pending'
                    }`}
                  >
                    {task.status === 'in_progress'
                      ? 'In Progress'
                      : task.status === 'completed'
                      ? 'Completed'
                      : 'Queued'}
                  </span>
                </td>
                <td>
                  <div className="branch-cell">
                    <GitBranch size={13} />
                    <span>{task.branch}</span>
                  </div>
                </td>
                <td>
                  <span className={`priority-badge priority-${task.priority}`}>
                    {task.priority.toUpperCase()}
                  </span>
                </td>
                <td>
                  <span className="time-text">{task.createdAt}</span>
                </td>
                <td>
                  <div className="agent-avatars-row">
                    {task.assignedAgents.map((ag, idx) => (
                      <span key={idx} className="agent-micro-chip">
                        {ag ? ag.split(' ')[0] : 'Agent'}
                      </span>
                    ))}
                  </div>
                </td>
                <td>
                  <button
                    className="table-action-btn"
                    onClick={() => onSelectRun && onSelectRun(task.id)}
                  >
                    <span>Detay</span>
                    <ArrowUpRight size={13} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
