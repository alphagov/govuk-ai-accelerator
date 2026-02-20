import os

Blue = "\033[34m"
Bold = "\033[1m"
Reset = "\033[0m"

def clean_content(output_dir):
    print("🛀 Cleaning content...")
    print("")

    files_cleaned = 0

    output_files = os.listdir("output")

    if output_files:
        for file in output_files:

            with open(output_dir + "/" + file, 'r') as content:
                lines = content.readlines()

            new_lines = []
            previous_line_blank = False

            for line in lines:
                new_line = line.strip()

                if new_line in {"Print this page", "Printable version"}:
                    continue

                if new_line == "":
                    if not previous_line_blank:
                        new_lines.append(line)
                    previous_line_blank = True
                else:
                    new_lines.append(line.lstrip())
                    previous_line_blank = False

            with open(output_dir + "/" + file, 'w') as content:
                content.writelines(new_lines)
                content.close()
            print("✅  " + Blue + Bold + file + Reset + " successfully cleaned")
            files_cleaned += 1

        print("")
        print("🧼 " + str(files_cleaned) + " files cleaned")
    else:
        print("⚠️ No content files found. Check the output directory")