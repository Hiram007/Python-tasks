#Prompt the user to:
#Enter the first number
first_num =int(input("Enter first number: "))

#Choose an operator: +, -, *, /
operator = input("Choose an operator +, -, *, /: ")

#Enter the second number
second_num = int(input("Enter second number: "))

#Perform the operation and print the result
if operator == '+':
    result =  first_num + second_num
    print("The result is:", result)
elif operator == '-':
    result =  first_num - second_num
    print("The result is:", result)
elif operator == '*':
    result =  first_num * second_num
    print("The result is:", result)
elif operator == '/':
    result =  first_num / second_num
    print("The result is:", result)

