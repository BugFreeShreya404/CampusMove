from campus import create_app

app = create_app()

if __name__ == "__main__":
    print("\n  Campus Parking & Transport Locator  ->  http://127.0.0.1:5004")
    print("  Demo logins: Shreya Kanade/shreya123, Abhijit More/abhijit123, admin/admin123\n")
    app.run(host="127.0.0.1", port=5004, debug=False, threaded=True)
