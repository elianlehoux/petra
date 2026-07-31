import sys, json, re
def main():
    try:
        data = json.loads(sys.stdin.read())
        text = data.get("text", "")
        res = {
            "from": re.search(r"From:\s*(.*)", text).group(1) if re.search(r"From:\s*(.*)", text) else "",
            "to": re.search(r"To:\s*(.*)", text).group(1) if re.search(r"To:\s*(.*)", text) else "",
            "subject": re.search(r"Subject:\s*(.*)", text).group(1) if re.search(r"Subject:\s*(.*)", text) else "",
        }
        print(json.dumps(res))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
if __name__ == "__main__":
    main()
