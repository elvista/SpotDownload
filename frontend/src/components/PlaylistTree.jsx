import { useMemo, useState, useCallback } from 'react';

function TreeNode({ node, children, selectedId, onSelect, depth = 0 }) {
  const [expanded, setExpanded] = useState(false);
  // Lexicon types: 1 = folder, 2 = playlist, 3 = smart list (selectable, has dynamic tracks)
  const isFolder = node.type === 1 || node.type === '1';
  const isSmartList = node.type === 3 || node.type === '3';
  const isSelected = node.id === selectedId;
  const hasChildren = children?.length > 0;

  const handleClick = useCallback(() => {
    if (isFolder) {
      setExpanded((prev) => !prev);
    } else if (isSmartList && hasChildren) {
      // Smart list with children: toggle folder AND select
      setExpanded((prev) => !prev);
      onSelect(node);
    } else {
      onSelect(node);
    }
  }, [isFolder, isSmartList, hasChildren, node, onSelect]);

  return (
    <div>
      <button
        type="button"
        onClick={handleClick}
        className={`w-full text-left flex items-center gap-2 px-2 py-1.5 rounded-md text-sm transition-colors ${
          isSelected
            ? 'bg-white/10 text-white'
            : 'text-spotify-light-gray hover:text-white hover:bg-white/5'
        }`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {isFolder ? (
          <svg
            className={`w-3.5 h-3.5 shrink-0 transition-transform ${expanded ? 'rotate-90' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        ) : isSmartList ? (
          <svg className="w-3.5 h-3.5 shrink-0 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
        ) : (
          <svg className="w-3.5 h-3.5 shrink-0 text-spotify-green" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55C7.79 13 6 14.79 6 17s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z" />
          </svg>
        )}
        <span className="truncate">{node.name}</span>
      </button>
      {isFolder && expanded && children?.length > 0 && (
        <div>
          {children.map((child) => (
            <TreeNode
              key={child.node.id}
              node={child.node}
              children={child.children}
              selectedId={selectedId}
              onSelect={onSelect}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function PlaylistTree({ playlists, selectedId, onSelect }) {
  const tree = useMemo(() => {
    if (!playlists?.length) return [];
    const byParent = {};
    for (const pl of playlists) {
      const parentKey = pl.parentId ?? 'root';
      if (!byParent[parentKey]) byParent[parentKey] = [];
      byParent[parentKey].push(pl);
    }
    for (const key of Object.keys(byParent)) {
      byParent[key].sort((a, b) => (a.position ?? 0) - (b.position ?? 0));
    }
    function build(parentId) {
      const items = byParent[parentId] || [];
      return items.map((pl) => ({
        node: pl,
        children: build(pl.id),
      }));
    }
    // Lexicon has a hidden ROOT node (type=1, parentId=null) — skip it and start from its children
    const roots = build('root');
    if (roots.length === 1 && roots[0].node.name === 'ROOT') {
      return roots[0].children;
    }
    return roots;
  }, [playlists]);

  if (!tree.length) {
    return <p className="text-sm text-spotify-light-gray/60 px-2">No playlists found</p>;
  }

  return (
    <div className="space-y-0.5">
      {tree.map((item) => (
        <TreeNode
          key={item.node.id}
          node={item.node}
          children={item.children}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}
