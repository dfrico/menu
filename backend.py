from flask import Flask, jsonify
from flask_cors import CORS
import json

from menu import generate_schedule

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "http://localhost:8000"}})

# Store the menu in memory
current_menu = None

@app.route('/menu', methods=['GET'])
def get_menu():
    global current_menu
    if current_menu is None:
        return jsonify({"error": "No menu generated yet. Please call /generate to create one."}), 404
    return jsonify(current_menu)

@app.route('/generate', methods=['GET'])
def generate_new_menu():
    global current_menu
    sched = generate_schedule()
    if isinstance(sched, dict):
        # Format the schedule into the required JSON structure
        formatted_schedule = {}
        for (week, day, time), dish in sched.items():
            if week not in formatted_schedule:
                formatted_schedule[week] = {}
            if day not in formatted_schedule[week]:
                formatted_schedule[week][day] = {}
            formatted_schedule[week][day][time] = dish

        # Update the current menu
        current_menu = formatted_schedule
        return jsonify({"message": "New menu generated successfully!", "menu": current_menu})
    else:
        return jsonify({"error": "Failed to generate menu"}), 500

if __name__ == '__main__':
    app.run(port=5001, debug=True)
