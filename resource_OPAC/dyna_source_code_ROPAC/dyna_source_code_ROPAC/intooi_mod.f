	MODULE INTOOI_MOD
c	 October 2002 by Yi-Chang Chiu

	TYPE TRANSFER ! Define the data structure for transferred vehicles
  	INTEGER VehID ! Vehicle ID
  	INTEGER InLink ! Link Id of the inbound link
  	INTEGER Order   ! order number on the original link for the vehicle ready to move in
	END TYPE TRANSFER

	TYPE LINKMEMBER
  	TYPE(TRANSFER),POINTER::P(:) ! size associated with the path length
  	INTEGER::PSize ! size of the allocated P()
	END TYPE LINKMEMBER
   
	TYPE(LINKMEMBER),ALLOCATABLE::TranLink_Array(:) ! Declare generic vehicle arrays

	INTEGER ::m_IncreaseSize = 5 ! increment for P() 
	INTEGER TranLink_ArraySize
	INTEGER vectorerror


	CONTAINS

c	 *** Start of TranLink_Array implementation ***

	SUBROUTINE TranLink_2DSetup(Size)

  	INTEGER Size
  	INTEGER :: vi
c	 Remove existing array
  	if(ALLOCATED(TranLink_Array))then
    	call TranLink_2DRemove()
  	endif

c	 Initialize increase size.
c	 Setup new array
  	if (.NOT. ALLOCATED(TranLink_Array)) then
    	ALLOCATE(TranLink_Array(Size),stat=vectorerror)
	if(vectorerror.ne.0) then
 	  write(911,*)"TranLink_Array Setup"
	  pause
	endif
  	endif
  
c	 Initialize new size for each element
  	do vi = 1, Size
   	TranLink_Array(vi)%PSize = 0
  	enddo

  	TranLink_ArraySIZE = Size
	

	END SUBROUTINE 

c	 this subroutine copies the existing array into a longer one
	SUBROUTINE TranLink_Setup(it,NewSize)
	
 	INTEGER it,NewSize,error
 	TYPE(TRANSFER),POINTER::tempP(:)
 	INTEGER::vi
 	INTEGER::OldSize
 	OldSize=0
	
c	 create temp pointer to store contents of array
   	if(TranLink_Array(it)%PSize>0)then
     	 OldSize = TranLink_Array(it)%PSize
     	 ALLOCATE(tempP(TranLink_Array(it)%PSize),stat=vectorerror)
	 if(vectorerror.ne.0) then
	   write(911,*) 'allocate tmpP vectorerror in TranLink_Setup'
	   stop
	 endif

c	 Copy content of old array to temp pointer
     	 do vi=1,TranLink_Array(it)%PSize
	   tempP(vi)%VehID = TranLink_Array(it)%P(vi)%VehID 
	   tempP(vi)%InLink = TranLink_Array(it)%P(vi)%InLink 
	   tempP(vi)%Order = TranLink_Array(it)%P(vi)%Order 
	 enddo
  
c	 Delete the old array
     	 if(associated(TranLink_Array(it)%P))then
	  DEALLOCATE(TranLink_Array(it)%P,stat=vectorerror)
	  if(vectorerror.ne.0)then
	    write(911,*)"deallocate TranLink_Array vector error"
	    pause
	  endif
     	 endif
	 
   	endif

c	 reallocate array
c	 Alex-release of memory
c	if(associated(TranLink_Array(it)%P))then
c	deallocate(TranLink_Array(it)%P,stat=error)
c	  if(error.ne.0)then
c	    write(911,*)"deallocate TranLink_Array(it)%P vector error"
c	    print *,"deallocate TranLink_Array(it)%P vector error"
c	    pause
c	  endif
c     endif


   	ALLOCATE(TranLink_Array(it)%P(NewSize),stat=vectorerror)
	if(vectorerror.ne.0) then
      	write(911,*) "allocate TranLink_Array vector error"
	  pause
	endif
   
c	 Copy contents from temp back to array 
   	do vi = 1, OldSize
     	TranLink_Array(it)%P(vi)%VehID  = tempP(vi)%VehID
     	TranLink_Array(it)%P(vi)%InLink = tempP(vi)%InLink
     	TranLink_Array(it)%P(vi)%Order  = tempP(vi)%Order
   	enddo

c	 initialize array for the remaining elements
   	do vi = OldSize +1, NewSize
     	TranLink_Array(it)%P(vi)%VehID  = 0
     	TranLink_Array(it)%P(vi)%InLink = 0
     	TranLink_Array(it)%P(vi)%Order  = 0
   	enddo

   	TranLink_Array(it)%PSize = NewSize

   	if(associated(tempP)) DEALLOCATE(tempP)

	END SUBROUTINE 

c	 This initialize the initial path arrays for vehicles


c	 This subroutine inserts a new element into the vehicle attribute array
	SUBROUTINE TranLink_Insert(it, Index1D, AttNo, Value)
 
  	INTEGER it, Index1D, AttNo, NewSize
  	integer    Value
  	if (Index1D > TranLink_Array(it)%PSize) then
	 NewSize = Index1D + m_IncreaseSize 
     	call TranLink_Setup(it,NewSize)
  	endif
 
  	if (AttNo.eq.1) then
    	TranLink_Array(it)%P(Index1D)%VehID  = Value
  	elseif (AttNo.eq.2) then
    	TranLink_Array(it)%P(Index1D)%InLink = Value
  	elseif (AttNo.eq.3) then
    	TranLink_Array(it)%P(Index1D)%Order  = Value
  	endif
	
	END SUBROUTINE 


c	 This function returns a value
	INTEGER FUNCTION TranLink_Value(it,Index1D,AttNo)
  	INTEGER it,Index1D,AttNo
  	REAL Value
  	if(Index1D>TranLink_Array(it)%PSize)then
     	write(911,*)"TranLink GetValue vector error"
     	write(911,*) 'Index1D =', Index1D
	write(911,*)'TranLink_Array(it)%PSize=',TranLink_Array(it)%PSize
     	stop
  	endif

  	if(AttNo.eq.1)then
     		TranLink_Value=TranLink_Array(it)%P(Index1D)%VehID
  	elseif(AttNo.eq.2)then
     		TranLink_Value=TranLink_Array(it)%P(Index1D)%InLink
  	elseif(AttNo.eq.3)then
     		TranLink_Value=TranLink_Array(it)%P(Index1D)%Order
  	else
    		write(911,*) 'get TranLink_value error'
    		pause
    		stop
  	endif

	END FUNCTION 


	INTEGER FUNCTION TranLink_Size(it)
   	i = TranLink_array(it)%PSize
   	do while (TranLink_array(it)%p(i)%VehID.lt.1) 
       i = i - 1
   	enddo
   	TranLink_Size = i

	END FUNCTION 

c	 -----------------------------------Remove
	SUBROUTINE TranLink_Remove(it)
 
  	INTEGER it
  	if (TranLink_Array(it)%PSize > 0) then
    	DEALLOCATE(TranLink_Array(it)%P,stat=vectorerror)
	if(vectorerror.ne.0) then
	  write(911,*)"deallocate TranLink_Array vectorerror"
	  write(911,*) it
	  pause
	endif
    	TranLink_Array(it)%PSize = 0 
  	endif

	END SUBROUTINE 

c	 -----------------------------------Clear
	SUBROUTINE TranLink_Clear(it,start)
 
  	INTEGER it
  	INTEGER start
  	INTEGER vi
c	 Clean the remaining elements     
   	do vi = start,TranLink_Array(it)%PSize
     	TranLink_Array(it)%P(vi)%VehID = 0 
     	TranLink_Array(it)%P(vi)%InLink = 0 
     	TranLink_Array(it)%P(vi)%Order = 0 
   	enddo

	END SUBROUTINE 

c	 -----------------------------------2DRemove
	SUBROUTINE TranLink_2DRemove()
 
  	INTEGER::vi
c	 Remove every element
  	do vi=1,TranLink_ArraySize
    	call TranLink_Remove(vi) 
  	enddo

c	Remove entire array
  	if (ALLOCATED(TranLink_Array)) then
    	DEALLOCATE(TranLink_Array,stat=vectorerror)
	if(vectorerror.ne.0) then
 	  write(911,*) "TranLink Destory"
 	  pause
	endif
  	endif
  	TranLink_ArraySize = 0
	
	END SUBROUTINE 

c *** End of TranLink_Array implementation ***

	END MODULE 
