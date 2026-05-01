package main

import (
	"bufio"
	"fmt"
	"log/slog"
	"net/http"
)

// proxySSE forwards a POST request to upstreamURL and streams the SSE response
// back to the client line by line, flushing after each line. This preserves the
// per-block streaming behavior of the FastAPI service end-to-end.
func proxySSE(w http.ResponseWriter, r *http.Request, upstreamURL string) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported by client", http.StatusInternalServerError)
		return
	}

	upstreamReq, err := http.NewRequestWithContext(r.Context(), http.MethodPost, upstreamURL, r.Body)
	if err != nil {
		http.Error(w, "failed to build upstream request", http.StatusInternalServerError)
		return
	}
	upstreamReq.Header.Set("Content-Type", "application/json")
	// Propagate request ID so traces are correlated across gateway and FastAPI logs.
	if id := w.Header().Get("X-Request-ID"); id != "" {
		upstreamReq.Header.Set("X-Request-ID", id)
	}

	resp, err := http.DefaultClient.Do(upstreamReq)
	if err != nil {
		slog.Error("upstream unreachable", "url", upstreamURL, "error", err)
		http.Error(w, "upstream unavailable", http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		http.Error(w, "upstream error", resp.StatusCode)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.WriteHeader(http.StatusOK)

	scanner := bufio.NewScanner(resp.Body)
	for scanner.Scan() {
		fmt.Fprintf(w, "%s\n", scanner.Text())
		flusher.Flush()
	}
	if err := scanner.Err(); err != nil {
		slog.Error("stream read error", "error", err)
	}
}
