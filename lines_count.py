# lines_count.py

def count_lines(filename):
    try:
        with open(filename, 'r') as file:
            return sum(1 for line in file)
    except FileNotFoundError:
        print(f"Error: The file '{filename}' does not exist.")
        return None
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

if __name__ == "__main__":
    filename = input("Please enter the name of your text file: ")
    line_count = count_lines(filename)
    
    if line_count is not None:
        print(f"The number of lines in '{filename}' is {line_count}")