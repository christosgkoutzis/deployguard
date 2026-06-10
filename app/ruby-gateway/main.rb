require 'sinatra'
require 'prometheus/client'
require 'prometheus/client/rack/exporter'
require 'net/http'
require 'json'

REGISTRY = Prometheus::Client.registry
HTTP_REQUESTS = REGISTRY.counter(
  :ruby_gateway_requests_total,
  docstring: 'Total HTTP requests received',
  labels: [:path]
)

# Kubernetes Service DNS name for the python-backend service
BACKEND_URL = ENV.fetch('BACKEND_URL', 'http://python-backend-service:80')

use Prometheus::Client::Rack::Exporter

set :port, 8000
set :bind, '0.0.0.0'

before { HTTP_REQUESTS.increment(labels: { path: request.path_info }) }

get '/health' do
  content_type :json
  { status: 'UP' }.to_json
end

get '/' do
  message = fetch_backend_message
  content_type :html
  <<~HTML
    <html>
      <body>
        <h1>Hello from Ruby Gateway!</h1>
        <p>Message from Python Backend: <strong>#{message}</strong></p>
      </body>
    </html>
  HTML
end

helpers do
  def fetch_backend_message
    uri = URI("#{BACKEND_URL}/message")
    response = Net::HTTP.get_response(uri)
    JSON.parse(response.body)['message']
  rescue => e
    "Backend unavailable: #{e.message}"
  end
end
