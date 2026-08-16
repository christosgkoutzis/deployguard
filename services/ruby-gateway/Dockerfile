FROM ruby:3.2-slim
WORKDIR /app
COPY Gemfile ./
RUN bundle install
COPY main.rb .
EXPOSE 8000
CMD ["ruby", "main.rb"]
