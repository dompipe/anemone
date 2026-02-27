from eng1neer import respond_subject_specific

def main():
    print("eng1neer chat (Ctrl-C to exit)")
    while True:
        try:
            prompt = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return

        if not prompt:
            continue

        try:
            reply = respond_subject_specific(prompt)
        except Exception as e:
            reply = f"[error] {type(e).__name__}: {e}"

        print(f"eng1neer> {reply}")

if __name__ == "__main__":
    main()