import datetime

def modify_observation_times(file_path):
    modified_data = []

    with open(file_path, 'r') as file:
        lines = file.readlines()

    i = 0
    while i < len(lines):
        try:
            # Skip empty lines
            if lines[i].strip() == '':
                i += 1
                continue

            # Trim whitespace and parse start and end times
            start_time_str = ' '.join(lines[i].strip().split(' ')[1:])
            end_time_str = ' '.join(lines[i + 1].strip().split(' ')[1:])

            start_time = datetime.datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S')
            end_time = datetime.datetime.strptime(end_time_str, '%Y-%m-%d %H:%M:%S')

            # Calculate the midpoint time
            midpoint = start_time + (end_time - start_time) / 2

            # Set new start and end times to be one minute centered on the midpoint
            new_start = midpoint - datetime.timedelta(seconds=120)
            new_end = midpoint + datetime.timedelta(seconds=120)

            # Modify the observation times in the data
            lines[i] = 'BEGINLOCAL ' + new_start.strftime('%Y-%m-%d %H:%M:%S') + '\n'
            lines[i + 1] = 'ENDLOCAL ' + new_end.strftime('%Y-%m-%d %H:%M:%S') + '\n'

            # Add the modified block and an empty line to the new data
            modified_data.extend(lines[i:i+6] + ['\n'])

            # Move to the next observation block
            i += 6

        except Exception as e:
            print("Error processing lines:", lines[i:i+6])
            print("Exception:", e)
            break  # Exit the loop for debugging

    # Write the modified data back to the file
    with open(file_path, 'w') as file:
        file.writelines(modified_data)

# Example usage
modify_observation_times('tleplan.txt')
