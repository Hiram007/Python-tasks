#Use input to get any two numbers from the user.
#Store these numbers in variables called num1 and num2 .
num1 = input("Enter a number: ")
num2 = input("Enter a second number: ")

#Print out the values of num1 and num2 before the swap.
print("Before the swap")
print("Num1 = " + num1)
print("Num2 = " + num2)

#swap
temp = num2
num2 = num1
num1 = temp


#Print the values of num1 and num2 after the swap.
print("After the swap")
print("Num1 = " + num1)
print("Num2 = " + num2)
