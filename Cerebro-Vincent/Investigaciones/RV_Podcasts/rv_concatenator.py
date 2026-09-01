import os


def concatenate_txt_files(directory_path=None):
    # Use the current working directory if no path is provided
    if directory_path is None:
        directory_path = os.getcwd()

    # Path for the resulting file
    output_file_path = os.path.join(directory_path, 'RV_Result.txt')

    # Create or overwrite the output file
    with open(output_file_path, 'w', encoding='utf-8') as output_file:
        # Iterate over each file in the directory
        for filename in sorted(os.listdir(directory_path)):
            if filename.endswith('.txt'):
                # Write the chapter title
                output_file.write(f"\n\n{'-' * 40}\n{filename}\n{'-' * 40}\n\n")

                # Path to the current file
                file_path = os.path.join(directory_path, filename)

                # Read and write the contents of the current file
                with open(file_path, 'r', encoding='utf-8') as file:
                    contents = file.read()
                    output_file.write(contents + "\n")

    print(f"Files concatenated successfully into '{output_file_path}'.")


# Example usage without providing a path
concatenate_txt_files()
