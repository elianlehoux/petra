import sys, json, re
def main():
    try:
        data = json.loads(sys.stdin.read())
        text = data.get("text", "")
        res = {
            "invoice_number": re.search(r"Invoice #(\w+)", text).group(1) if re.search(r"Invoice #(\w+)", text) else "",
            "date": re.search(r"Date: (\S+)", text).group(1) if re.search(r"Date: (\S+)", text) else "",
        }
        print(json.dumps(res))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
if __name__ == "__main__":
    main()
