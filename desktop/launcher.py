from paths import get_user_data_dir


def main():
    data_dir = get_user_data_dir()

    print("Kalshi Desktop Launcher")
    print(f"Data directory: {data_dir}")


if __name__ == "__main__":
    main()