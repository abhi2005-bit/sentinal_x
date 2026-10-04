import React, { useState, useEffect, useRef } from 'react';
import TaskGraph from './TaskGraph';
import { Play, Square, Loader, AlertTriangle, ShieldAlert, Cpu } from 'lucide-react';

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [graphData, setGraphData] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [decision, setDecision] = useState<any>(null);
  const [customEvent, setCustomEvent] = useState("");
  const ws = useRef<WebSocket | null>(null);

  // Initialize session on load
  useEffect(() => {
    initSession();
  }, []);

  const initSession = async () => {
    try {
      const res = await fetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal: "Plan Chennai to Delhi trip" })
      });
      const data = await res.json();
      setSessionId(data.session_id);
      connectWebSocket(data.session_id);
      fetchGraph(data.session_id);
      setEvents([{ type: 'INFO', msg: 'Session created: ' + data.session_id }]);
      setDecision(null);
    } catch (e) {
      console.error(e);
      setEvents([{ type: 'ERROR', msg: 'Failed to connect to backend.' }]);
    }
  };

  const connectWebSocket = (sid: string) => {
    if (ws.current) ws.current.close();
    ws.current = new WebSocket(`ws://${window.location.host}/ws/${sid}`);
    ws.current.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      const eType = payload.event_type || payload.type;

      if (['TASK_STARTED', 'TASK_COMPLETED', 'TASK_INVALIDATED', 'TASK_PRESERVED', 'TASK_CANCELLED', 'REPLAN_COMPLETED', 'SESSION_RESUMED'].includes(eType)) {
        fetchGraph(sid);
      } else if (eType === 'INTERVENTION_SELECTED') {
        setDecision(payload.data);
      }
      
      setEvents(prev => [...prev, {
        type: 'WS',
        msg: `[${eType}] ${JSON.stringify(payload.data || {})}`
      }]);
    };
  };

  const fetchGraph = async (sid: string) => {
    const res = await fetch(`/api/sessions/${sid}`);
    setGraphData(await res.json());
  };

  const startExecution = async () => {
    if (!sessionId) return;
    await fetch(`/api/sessions/${sessionId}/start`, { method: 'POST' });
  };

  const injectEvent = async (text: string) => {
    if (!sessionId) return;
    await fetch(`/api/sessions/${sessionId}/interrupt`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ raw_text: text })
    });
  };

  return (
    <div className="dashboard-container">
      {/* Left: Graph */}
      <div className="graph-section glass-panel">
        <h2 style={{ position: 'absolute', top: 16, left: 16, zIndex: 10 }}>
          <Cpu size={24} /> SENTINEL-X Control Room
        </h2>
        <TaskGraph graphData={graphData} />
      </div>

      {/* Right: Controls & Logs */}
      <div className="sidebar">
        
        {/* Actions */}
        <div className="card glass-panel button-group">
          <h2>Actions</h2>
          <button className="primary" onClick={startExecution}>
            <Play size={16} /> Start Execution
          </button>
          <button onClick={initSession}>
            <Loader size={16} /> Reset Session
          </button>
        </div>

        {/* Semantic Injection */}
        <div className="card glass-panel button-group">
          <h2><ShieldAlert size={18} /> Inject Interruption</h2>
          <button className="danger" onClick={() => injectEvent("Do not book anything.")}>
            Demo: "Do not book anything" (Mid-plan)
          </button>
          <button className="danger" onClick={() => injectEvent("Stop the booking.")}>
            Demo: "Stop the booking" (Late Interrupt)
          </button>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <input 
              type="text" 
              value={customEvent}
              onChange={(e) => setCustomEvent(e.target.value)}
              placeholder="Custom event..."
              style={{ flex: 1, padding: 8, borderRadius: 6, border: '1px solid #333', background: '#111', color: '#fff' }}
            />
            <button onClick={() => injectEvent(customEvent)}>Send</button>
          </div>
        </div>

        {/* Decision Banner */}
        {decision && (
          <div className="card glass-panel">
            <h2>Semantic Impact Result</h2>
            <div className="decision-banner">
              <div><strong>Event Type:</strong> {decision.event_type}</div>
              <div><strong>Decision:</strong> {decision.decision}</div>
              <div><strong>Preserved Tasks:</strong> {decision.preserved_tasks}</div>
              <div><strong>Preempted Tasks:</strong> {decision.preempted_tasks}</div>
            </div>
          </div>
        )}

        {/* Event Log */}
        <div className="card glass-panel" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <h2>Event Timeline</h2>
          <div className="event-log">
            {events.map((e, i) => (
              <div key={i} className={`log-entry ${e.type.toLowerCase()}`}>
                {e.msg}
              </div>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}
