// Scouter gateway — external-facing HTTP server that proxies to the FastAPI
// harness and adds request ID injection and timing middleware.
//
// Usage:
//
//	go run . [-port 8080] [-upstream http://localhost:8001]
package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	port := flag.Int("port", 8080, "gateway listen port")
	upstream := flag.String("upstream", "http://localhost:8001", "FastAPI upstream base URL")
	flag.Parse()

	mux := http.NewServeMux()

	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"status":"ok"}`)
	})

	mux.HandleFunc("POST /ask", func(w http.ResponseWriter, r *http.Request) {
		proxySSE(w, r, *upstream+"/ask")
	})

	srv := &http.Server{
		Addr:         fmt.Sprintf(":%d", *port),
		Handler:      requestID(mux),
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 5 * time.Minute, // generous for long SSE streams
		IdleTimeout:  120 * time.Second,
	}

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		slog.Info("gateway listening", "port", *port, "upstream", *upstream)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("server error", "error", err)
			os.Exit(1)
		}
	}()

	<-quit
	slog.Info("shutting down")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		slog.Error("shutdown error", "error", err)
	}
}
