require 'sinatra'
require 'net/http'
require 'json'

# Kubernetes Service DNS name for the python-backend service
BACKEND_URL = ENV.fetch('BACKEND_URL', 'http://python-backend-service:80')

set :port, 8000
set :bind, '0.0.0.0'

get '/health' do
  content_type :json
  { status: 'UP' }.to_json
end

get '/' do
  message = fetch_backend_message
  mocked_greeting = fetch_mocked_greeting
  db_message = params[:db_message] || ""
  content_type :html
  <<~HTML
    <html>
      <body>
        <h3>Hello from Ruby Gateway!</h3>
        <h3>Message from Python Backend: <strong>#{message}</strong></h3>
        <h4>Greeting from External Mock API: <strong>#{mocked_greeting}</strong></h4>
        <hr/>
        <h3>Database Actions</h3>
        <form action="/write" method="POST" style="display:inline;">
          <button type="submit">Write Greeting</button>
        </form>
        <form action="/read" method="GET" style="display:inline;">
          <button type="submit">Read Latest Greeting</button>
        </form>
        <p><i>#{db_message}</i></p>
      </body>
    </html>
  HTML
end

post '/write' do
  uri = URI("#{BACKEND_URL}/db/write")
  Net::HTTP.post(uri, "")
  redirect '/?db_message=Successfully wrote to database'
end

get '/read' do
  uri = URI("#{BACKEND_URL}/db/read")
  response = Net::HTTP.get_response(uri)
  data = JSON.parse(response.body)
  
  if data['error']
    msg = data['error']
  else
    msg = "#{data['greeting']} | Status: [#{data['status']}] | Created: #{data['created_at']}"
  end
  
  redirect "/?db_message=#{URI.encode_www_form_component(msg)}"
end

helpers do
  def fetch_backend_message
    uri = URI("#{BACKEND_URL}/message")
    response = Net::HTTP.get_response(uri)
    JSON.parse(response.body)['message']
  rescue => e
    "Backend unavailable: #{e.message}"
  end

  def fetch_mocked_greeting
    uri = URI("#{BACKEND_URL}/mock-greeting")
    response = Net::HTTP.get_response(uri)
    data = JSON.parse(response.body)
    data['greeting'] || data['error'] || 'No greeting available'
  rescue => e
    "Mocked Greeting API unavailable: #{e.message}"
  end
end
