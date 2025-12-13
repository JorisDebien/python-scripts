"""
Simple weather checker that fetches current weather data for a specified city using OpenWeatherMap API.
"""
import requests
import yaml

def load_config():
    with open('config.yml', 'r') as file:
        return yaml.safe_load(file)

def check_weather(api_key, city):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
    response = requests.get(url)
    return response.json()

def print_results(weather_data):
    if weather_data.get('cod') != 200:
        print("Error:", weather_data.get('message'))
    else:
        city = weather_data['name']
        temperature = weather_data['main']['temp']
        description = weather_data['weather'][0]['description']
        print(f"Weather in {city}: {temperature}°C, {description}")

if __name__ == "__main__":
    config = load_config()
    api_key = config['api_key']
    city = config['city']
    weather_data = check_weather(api_key, city)
    print_results(weather_data)
