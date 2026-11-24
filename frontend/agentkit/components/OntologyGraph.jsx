import React, {useEffect, useRef, useState} from "react";

import {createSigmaOntologyRenderer} from "@boulderaitech/ontology-graph";

import {buildGraph} from "../../src/ontologyGraphModel.js";
import {fetchSubgraph} from "../api.js";
import {subgraphRequest} from "../results.js";

/**
 * Ontology subgraph for one hit.
 *
 * Uses the same shared renderer and graph model as the Pro UI workbench, so a
 * node means the same thing on both pages.  The payload comes from
 * /api/ontology/subgraph and is re-checked against the current session.
 */
export default function OntologyGraph({hit, sessionId, onClose}) {
  const canvasRef = useRef(null);
  const rendererRef = useRef(null);
  const [payload, setPayload] = useState(null);
  const [status, setStatus] = useState("loading");
  const [message, setMessage] = useState("正在加载本体子图…");
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    const request = subgraphRequest(hit, sessionId);
    if (!request) {
      setStatus("error");
      setMessage("该本体编码无法定位子图，请从命中列表重新选择。");
      return undefined;
    }
    const controller = new AbortController();
    setStatus("loading");
    setMessage("正在加载本体子图…");
    setPayload(null);
    setSelected(null);
    fetchSubgraph(request, controller.signal)
      .then((data) => {
        const nodes = Array.isArray(data.nodes) ? data.nodes : [];
        const links = Array.isArray(data.links) ? data.links : [];
        if (!nodes.length) {
          setStatus("empty");
          setMessage("当前本体没有可展示的关联节点。");
          return;
        }
        setPayload(data);
        setStatus("ready");
        setMessage(`${nodes.length} 个节点 · ${links.length} 条关系 · 点击节点查看定义`);
      })
      .catch((error) => {
        if (error?.name === "AbortError") return;
        setStatus("error");
        setMessage(`子图加载失败：${error.message}`);
      });
    return () => controller.abort();
  }, [hit, sessionId]);

  useEffect(() => {
    if (status !== "ready" || !payload || !canvasRef.current) return undefined;
    let renderer = null;
    try {
      const graph = buildGraph(payload);
      renderer = createSigmaOntologyRenderer(canvasRef.current, graph);
      renderer.instance.on("clickNode", ({node}) => {
        const entity = (payload.nodes || []).find((item) => (item.id || item.code) === node);
        setSelected(entity || null);
      });
      rendererRef.current = renderer;
    } catch (error) {
      console.warn("ontology subgraph render failed", error);
      setStatus("error");
      setMessage("当前浏览器无法渲染关系图，命中列表仍可查看定义。");
    }
    return () => {
      renderer?.kill();
      rendererRef.current = null;
    };
  }, [status, payload]);

  return (
    <div className="ak-graph" role="dialog" aria-label="本体子图">
      <div className="ak-graph-panel">
        <header className="ak-graph-head">
          <div>
            <h3 className="ak-graph-title">{hit?.name || hit?.code || "本体子图"}</h3>
            <p className="ak-graph-sub">{hit?.code} · {message}</p>
          </div>
          <div className="ak-graph-actions">
            <button
              type="button"
              className="ak-ghost"
              onClick={() => rendererRef.current?.instance.getCamera().animatedReset({duration: 250})}
              disabled={status !== "ready"}
            >
              重置视图
            </button>
            <button type="button" className="ak-ghost" onClick={onClose}>关闭</button>
          </div>
        </header>
        <div className="ak-graph-body">
          <div className="ak-graph-canvas" ref={canvasRef} role="img" aria-label="本体关系图，可拖动缩放" />
          {status !== "ready" ? (
            <p className="ak-graph-status" role="status">{message}</p>
          ) : null}
          {selected ? (
            <aside className="ak-graph-detail">
              <strong>{selected.name || selected.code}</strong>
              <dl>
                <dt>编码</dt><dd>{selected.code || selected.id}</dd>
                <dt>类型</dt><dd>{selected.type || "unknown"}</dd>
                {selected.properties?.description ? (
                  <>
                    <dt>说明</dt><dd>{selected.properties.description}</dd>
                  </>
                ) : null}
              </dl>
            </aside>
          ) : null}
        </div>
      </div>
    </div>
  );
}
