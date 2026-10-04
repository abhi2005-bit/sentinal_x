import React, { useEffect, useState, useCallback, useRef } from 'react';
import { ReactFlow, MiniMap, Controls, Background, useNodesState, useEdgesState, MarkerType } from '@xyflow/react';
import { Play, Square, Loader, AlertTriangle, MessageSquare, TerminalSquare } from 'lucide-react';

const nodeTypes = {
  task: ({ data }: any) => {
    return (
      <div className={`task-node ${data.status}`}>
        <div className="task-node-header">
          <span>{data.type}</span>
          <span>{data.status}</span>
        </div>
        <div className="task-node-title">{data.label}</div>
      </div>
    );
  }
};

export default function TaskGraph({ graphData }: { graphData: any }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  useEffect(() => {
    if (!graphData || !graphData.tasks) return;
    
    // Auto-layout is complex, so we'll do a simple hardcoded grid based on our demo graph for now
    // In a real app we'd use dagre.js or similar for layout.
    const layout: Record<string, {x: number, y: number}> = {
      search_flights: { x: 100, y: 100 },
      compare_flights: { x: 300, y: 100 },
      book_flight: { x: 500, y: 50 },
      create_itinerary: { x: 700, y: 150 },
      search_hotel: { x: 100, y: 250 },
      compare_hotel: { x: 300, y: 250 },
      book_hotel: { x: 500, y: 250 },
      process_payment: { x: 500, y: 350 },
      send_email: { x: 700, y: 250 },
      add_to_calendar: { x: 700, y: 350 },
    };

    const newNodes = Object.keys(graphData.tasks).map((tid, idx) => {
      const task = graphData.tasks[tid];
      const pos = layout[tid] || { x: 100 + (idx * 50), y: 100 + (idx * 50) };
      return {
        id: tid,
        type: 'task',
        position: pos,
        data: { label: task.description, status: task.status, type: task.task_type }
      };
    });

    const newEdges: any[] = [];
    Object.keys(graphData.tasks).forEach((tid) => {
      const task = graphData.tasks[tid];
      task.dependencies.forEach((dep: string) => {
        newEdges.push({
          id: `e-${dep}-${tid}`,
          source: dep,
          target: tid,
          animated: task.status === 'RUNNING',
          style: { stroke: 'rgba(255,255,255,0.4)', strokeWidth: 2 },
          markerEnd: { type: MarkerType.ArrowClosed, color: 'rgba(255,255,255,0.4)' },
        });
      });
    });

    setNodes(newNodes);
    setEdges(newEdges);
  }, [graphData]);

  return (
    <div style={{ width: '100%', height: '100%' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
      >
        <Background color="#ccc" gap={16} />
        <Controls />
      </ReactFlow>
    </div>
  );
}
