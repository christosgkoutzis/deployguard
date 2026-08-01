require 'sinatra'
require 'net/http'
require 'json'

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
  search_results = params[:search_results] || ""
  
  content_type :html
 <<~HTML
    <html>
      <body style="font-family: sans-serif; padding: 20px;">
        <h2>DeployGuard Architecture Demo</h2>
        <p><strong>Python Backend says:</strong> #{message}</p>
        <p><strong>External API Mock says:</strong> #{mocked_greeting}</p>
        <hr/>
        
        <h3>1. Relational DB & Event-Driven Write (Postgres + Kafka)</h3>
        <form action="/write" method="POST" style="display:inline;">
          <input type="text" name="greeting_text" placeholder="Type your greeting..." required>
          <button type="submit">Write Custom Event</button>
        </form>
        
        <h3>2. Cached Read (Redis)</h3>
        <form action="/read" method="GET" style="display:inline;">
          <button type="submit">Read Latest Greeting</button>
        </form>
        <p style="color: blue;"><i>#{db_message}</i></p>
        
        <hr/>
        <h3>3. Full-Text Search (Elasticsearch)</h3>
        <form action="/search" method="GET">
          <input type="text" name="q" placeholder="Search greetings..." required>
          <button type="submit">Search</button>
        </form>
        <div style="background-color: #f4f4f4; padding: 10px;">
          #{search_results}
        </div>

        <hr/>
        <h3>4. Enterprise Export (SQS & S3)</h3>
        <form action="/report/generate" method="POST" style="display:inline;">
          <button type="submit">1. Generate CSV Report (Async)</button>
        </form>
        <form action="/report/download" method="GET" style="display:inline;">
          <button type="submit">2. Download Latest CSV</button>
        </form>
      </body>
    </html>
  HTML
end

post '/write' do
  uri = URI("#{BACKEND_URL}/db/write")
  req = Net::HTTP::Post.new(uri, 'Content-Type' => 'application/json')
  req.body = { greeting: params[:greeting_text] }.to_json
  Net::HTTP.start(uri.hostname, uri.port) do |http|
    http.request(req)
  end
  redirect '/?db_message=Successfully+triggered+write+event'
end

post '/report/generate' do
  uri = URI("#{BACKEND_URL}/report/generate")
  Net::HTTP.post(uri, "")
  redirect '/?db_message=Report+generation+queued+in+SQS'
end

get '/report/download' do
  uri = URI("#{BACKEND_URL}/report/download")
  response = Net::HTTP.get_response(uri)
  data = JSON.parse(response.body)
  if data['download_url']
    redirect data['download_url']
  else
    redirect '/?db_message=Report+not+ready+or+error'
  end
end

get '/read' do
  uri = URI("#{BACKEND_URL}/db/read")
  response = Net::HTTP.get_response(uri)
  data = JSON.parse(response.body)
  
  if data['error']
    msg = data['error']
  else
    msg = "Status: #{data['status']} | Source: #{data['source'] || 'Unknown'}"
  end
  redirect "/?db_message=#{URI.encode_www_form_component(msg)}"
end

get '/search' do
  query = params[:q]
  uri = URI("#{BACKEND_URL}/search?q=#{URI.encode_www_form_component(query)}")
  response = Net::HTTP.get_response(uri)
  data = JSON.parse(response.body)
  
  if data['error']
    results = "<p style='color:red;'>#{data['error']}</p>"
  elsif data['results'] && data['results'].empty?
    results = "<p>No results found for '#{query}'.</p>"
  else
    results = "<ul>"
    data['results'].each do |res|
      results += "<li>ID: #{res['id']} | Status: #{res['status']}</li>"
    end
    results += "</ul>"
  end
  
  redirect "/?search_results=#{URI.encode_www_form_component(results)}"
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
    JSON.parse(response.body)['greeting'] || 'No greeting available'
  rescue => e
    "Mocked API unavailable: #{e.message}"
  end
end