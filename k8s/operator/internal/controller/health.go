package controller

import (
	"context"
	"fmt"
	"net/http"
	"time"
)

// HealthProber checks one URL. A nil error means the service is healthy.
type HealthProber interface {
	Check(ctx context.Context, url string) error
}

// HTTPProber sends a GET request and treats any 2xx answer as healthy.
type HTTPProber struct {
	Client *http.Client
}

// NewHTTPProber returns a prober with a 5 second timeout that does not follow redirects,
// so a moved page counts as a failure.
func NewHTTPProber() *HTTPProber {
	return &HTTPProber{Client: &http.Client{
		Timeout: 5 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}}
}

// Check performs the GET request and returns an error for anything but a 2xx answer.
func (p *HTTPProber) Check(ctx context.Context, url string) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	client := p.Client
	if client == nil {
		client = NewHTTPProber().Client
	}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return fmt.Errorf("GET %s returned %d", url, resp.StatusCode)
	}
	return nil
}
