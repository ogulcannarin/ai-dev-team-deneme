import React from 'react';
import { FileCode, Search } from 'lucide-react';
import { MOCK_PROJECT_FILES } from '../../data/mockData';

export const FilesView: React.FC = () => {
  const [search, setSearch] = React.useState('');

  const filteredFiles = MOCK_PROJECT_FILES.filter((f) =>
    f.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="view-container">
      <div className="view-header">
        <div>
          <h2 className="view-title">Project Workspace Files</h2>
          <p className="view-subtitle">
            AI Dev Team tarafından indekslenen ve üzerinde değişiklik yapılan proje dosyaları
          </p>
        </div>
        <div className="search-bar-wrap">
          <Search size={14} className="search-icon" />
          <input
            type="text"
            className="search-input"
            placeholder="Dosya adına göre ara..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      <div className="files-table-card">
        <table className="files-table">
          <thead>
            <tr>
              <th>Dosya Yolu</th>
              <th>Tür</th>
              <th>Boyut</th>
              <th>Son Değişiklik</th>
              <th>Durum</th>
            </tr>
          </thead>
          <tbody>
            {filteredFiles.map((file, idx) => (
              <tr key={idx} className="file-row">
                <td>
                  <div className="file-name-cell">
                    <FileCode size={16} className="file-icon" />
                    <span className="file-name">{file.name}</span>
                  </div>
                </td>
                <td>
                  <span className="file-type-pill">{file.type.toUpperCase()}</span>
                </td>
                <td>
                  <span className="file-size-text">{file.size}</span>
                </td>
                <td>
                  <span className="file-time-text">{file.modified}</span>
                </td>
                <td>
                  <span
                    className={`status-pill ${
                      file.status === 'modified'
                        ? 'running'
                        : file.status === 'added'
                        ? 'completed'
                        : 'pending'
                    }`}
                  >
                    {file.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
