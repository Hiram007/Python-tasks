#Ask the user to enter three different integers
num1 = int(input("Enter first integer: "))
num2 = int(input("Enter second integer: "))
num3 = int(input("Enter third integer: "))

#Now print out:
#The sum of all the numbers
int_sum = num1 + num2 + num3
print("Sum of three integers: ", int(int_sum) )

#The first number minus the second number
int_min = num1 - num2
print("The first number minus the second number: " , int_min )

#The third number multiplied by the first number
int_mul = num3 * num1
print("The third number multiplied by the first number: " , int_mul)

#The sum of all three numbers divided by the third number
int_div = int_sum / num3
print("The sum of all three numbers divided by the third number: " ,int_div)

