      MODULE VECTOR_MOD
c	! Sept 2001 --  by Xuesong Zhou and Yi-Chang Chiu
c --
	TYPE Attribute ! Define the data structure for generic vehicles
  	INTEGER PathNode ! Node numbers
  	REAL    PathStop ! Stop time at each node
  	REAL    PathTime ! Time stamp at each node
  	REAL    PathTimeDiff ! travel time between nodes
	END TYPE Attribute
c --
	TYPE MEMBER
  	TYPE(Attribute),POINTER::P(:) ! size associated with the path length
  	INTEGER::PSize ! size of the allocated P()
	END TYPE MEMBER
c --
	TYPE(MEMBER),ALLOCATABLE::VhcAtt_Array(:) ! Declare generic vehicle arrays
c --
	TYPE BusAttribute ! Define the data structure for bus
  	INTEGER PathNode ! Node numbers of the bus path
  	INTEGER StopMode
	END TYPE
c	! --  StopMode: an operation index for each link along the path.
c	! --                it allows to specify where the bus stop is located
c	! --                in the link, according to the following indicators.
c	! --   =0, no stop
c	! --   =1, stop near the downstream end of the link.
c	! --   =2, stop at the middle of the link
c	! --   =3, stop at the middle of the link with bus bay.
c --
	TYPE BUSMEMBER
  	TYPE(BusAttribute),POINTER::P(:)
  	INTEGER::PSize
	END TYPE BUSMEMBER
c --
	TYPE(BUSMEMBER),ALLOCATABLE::BusAtt_Array(:) ! Declare Bus Arrays
c --
	INTEGER::m_IncreaseSize=5 ! increment for P() 
	INTEGER VhcAtt_ArraySize
	INTEGER vectorerror
	INTEGER BusAtt_ArraySize
c --
	CONTAINS
c --
c	! *** Start of VhcAtt_Array implementation ***
c --
c	! This initialize the initial path arrays for vehicles
	SUBROUTINE VhcAtt_2DSetup(SSize)
c --
  	INTEGER SSize
  	INTEGER::vi
C	SSize=SSize+1000
c	! Remove existing array
  	if(ALLOCATED(VhcAtt_Array))then
    	call VhcAtt_2DRemove()
  	endif
c --
c	! Initialize increase size.
c	! Setup new array
  	if(.NOT.ALLOCATED(VhcAtt_Array))then
C	print *, 'Alex01',SSize
    	ALLOCATE(VhcAtt_Array(SSize),stat=vectorerror)
	if(vectorerror.ne.0) then
 	  write(911,*)"VhcAtt Setup"
	  pause
	endif
  	endif
c --
c	! Initialize new size for each element
C	print *, 'Alex02',SSize
  	do vi=1,SSize
   	VhcAtt_Array(vi)%PSize=0
  	enddo
c --
  	VhcAtt_ArraySIZE=SSize
c --
	END SUBROUTINE 
c --
c	! this subroutine copies the existing array into a longer one
	SUBROUTINE VhcATT_Setup(it,NewSize)
	
 	INTEGER it,NewSize
 	TYPE(Attribute),POINTER::tempP(:)
 	INTEGER::vi
 	INTEGER::OldSize
 	OldSize=0
	
c	! create temp pointer to store contents of array
   	if(VhcAtt_Array(it)%PSize>0)then
     	OldSize = VhcAtt_Array(it)%PSize
C	print *,'Alex006'
     	ALLOCATE(tempP(VhcAtt_Array(it)%PSize),stat=vectorerror)
C	print *,'Alex007'
	 if(vectorerror.ne.0) then
	   write(911,*) 'allocate tmpP vectorerror'
	   stop
	 endif

c	! Copy content of old array to temp pointer
     	do vi = 1, VhcAtt_Array(it)%PSize
	   tempP(vi)%PathNode =VhcAtt_Array(it)%P(vi)%PathNode 
	   tempP(vi)%PathStop =VhcAtt_Array(it)%P(vi)%PathStop 
	   tempP(vi)%PathTime =VhcAtt_Array(it)%P(vi)%PathTime 
	tempP(vi)%PathTimeDiff=VhcAtt_Array(it)%P(vi)%PathTimeDiff 
	enddo

c	! Delete the old array
     	if(associated(VhcAtt_Array(it)%P))then
	  DEALLOCATE(VhcAtt_Array(it)%P,stat=vectorerror)
C	print *,'Alex07'
	  if(vectorerror.ne.0)then
	    write(911,*)"deallocate VhcAtt_1DArray vector error"
	    pause
	  endif
     	endif
   	endif

c	! reallocate array
C	print *, 'Alex002',it,NewSize,SSize

     	if(associated(VhcAtt_Array(it)%P))then
	  DEALLOCATE(VhcAtt_Array(it)%P,stat=vectorerror)
C	print *,'Alex07'
	  if(vectorerror.ne.0)then
	    write(911,*)"deallocate VhcAtt_1DArray vector error"
	    pause
	  endif
     	endif


   	ALLOCATE(VhcAtt_Array(it)%P(NewSize),stat=vectorerror)
	if(vectorerror.ne.0)then
      	write(911,*) "allocate VhcAtt_1DArray vector error"
	  pause
	endif

c	! Copy contents from temp back to array 
   	do vi = 1,OldSize
c	if (it.eq.42) then
c	print *,'Alex100',tempP(vi)%PathNode
c	endif
     	VhcAtt_Array(it)%P(vi)%PathNode = tempP(vi)%PathNode
     	VhcAtt_Array(it)%P(vi)%PathStop = tempP(vi)%PathStop
     	VhcAtt_Array(it)%P(vi)%PathTime = tempP(vi)%PathTime
     	VhcAtt_Array(it)%P(vi)%PathTimeDiff=tempP(vi)%PathTimeDiff
   	enddo

c	! initialize array for the remaining elements
   	do vi=OldSize+1,NewSize
c	if (it.eq.42) then
c	print *,'Alex50-here-0'
c	endif
      	VhcAtt_Array(it)%P(vi)%PathNode = 0
      	VhcAtt_Array(it)%P(vi)%PathStop = 0
      	VhcAtt_Array(it)%P(vi)%PathTime = 0
      	VhcAtt_Array(it)%P(vi)%PathTimeDiff = 0
   	enddo

C	print *, 'Alex009-update',it,NewSize,SSize
   	VhcAtt_Array(it)%PSize = NewSize

   	if(associated(tempP)) DEALLOCATE(tempP)

	END SUBROUTINE 

c	! This subroutine inserts a new element into the vehicle attribute array
	SUBROUTINE VhcAtt_Insert(it,Index1D,AttNo,Value)

  	INTEGER it, Index1D, AttNo, NewSize
  	REAL Value

  	if (Index1D > VhcAtt_Array(it)%PSize) then
	NewSize = Index1D + m_IncreaseSize 
C	print *, 'Alex11132430122a'
     	call VhcAtt_Setup(it,NewSize)
C	print *, 'Alex11132430123b'
  	endif

C	print *, 'Alex122',Index1D,'-here=',VhcAtt_Array(it)%PSize
C 	print *, 'Alex11132430124'

  	if (AttNo.eq.1) then
c	if (it.eq.42) then
c 	print *, 'Alex300',it,Index1D,AttNo,Value
c	endif
    	VhcAtt_Array(it)%P(Index1D)%PathNode=nint(Value)
  	elseif (AttNo.eq.2) then
C 	print *, 'Alex111324301242'
    	VhcAtt_Array(it)%P(Index1D)%PathStop = Value
  	elseif (AttNo.eq.3) then
C 	print *, 'Alex111324301243'
    	VhcAtt_Array(it)%P(Index1D)%PathTime = Value
  	elseif (AttNo.eq.4) then
C	print *, 'Alex111324301244'
    	VhcAtt_Array(it)%P(Index1D)%PathTimeDiff = Value
  	endif
C	print *, 'Alex123-here=',VhcAtt_Array(it)%PSize	
	END SUBROUTINE 


c	! This function returns a value
      REAL FUNCTION VhcAtt_Value(it,Index1D,AttNo)
      INTEGER it,Index1D,AttNo
      REAL Value
      if(Index1D > VhcAtt_Array(it)%PSize)then
	  print *,'Alex-error',Index1D,VhcAtt_Array(it)%PSize
     	write(911,*)"VhcAtt GetValue vector error"
     	write(911,*) 'Index1D =', Index1D
	write(911,*)'VhcAtt_Array(it)%PSize=',VhcAtt_Array(it)%PSize
     	stop
      endif
c	if(it.eq.213)print *, 'Alex400',it,Index1D,AttNo
      if(AttNo.eq.1)then
c	if(it.eq.213)print *, 'Alex401',
c     +  VhcAtt_Array(it)%P(Index1D)%PathNode

     	VhcAtt_Value = float(VhcAtt_Array(it)%P(Index1D)%PathNode)
      elseif(AttNo.eq.2)then
c	if(it.eq.213)print *, 'Alex402',
c     +  VhcAtt_Array(it)%P(Index1D)%PathStop
     	VhcAtt_Value = VhcAtt_Array(it)%P(Index1D)%PathStop
      elseif (AttNo.eq.3) then
c	if(it.eq.213)print *, 'Alex403',
c     +  VhcAtt_Array(it)%P(Index1D)%PathTime
     	VhcAtt_Value = VhcAtt_Array(it)%P(Index1D)%PathTime
      elseif (AttNo.eq.4) then
c	if(it.eq.213)print *, 'Alex404',
c     +  VhcAtt_Array(it)%P(Index1D)%PathTimeDiff
     	VhcAtt_Value = VhcAtt_Array(it)%P(Index1D)%PathTimeDiff
      else
    	write(911,*) 'get VhcAtt_value error'
    	stop
      endif
c	if(it.eq.213)print *,'Alex405',VhcAtt_Value
      END FUNCTION 


	INTEGER FUNCTION VhcAtt_Size(it)
   	i = VhcAtt_array(it)%PSize
   	do while (VhcAtt_array(it)%p(i)%PathNode.lt.1) 
       	i = i - 1
   	enddo
   	VhcAtt_Size = i

	END FUNCTION 

c	! -----------------------------------Remove
	SUBROUTINE VhcAtt_Remove(it)
 
  	INTEGER it
  	if(VhcAtt_Array(it)%PSize>0)then
    	DEALLOCATE(VhcAtt_Array(it)%P,stat=vectorerror)
	if(vectorerror.ne.0) then
	  write(911,*)"deallocate VhcAtt_Array vectorerror"
	  write(911,*) it
	  pause
	endif
c	print *,'Alex08'
    	VhcAtt_Array(it)%PSize = 0 
  	endif

	END SUBROUTINE 

c	! -----------------------------------Clear
	SUBROUTINE VhcAtt_Clear(it,start)

  	INTEGER it
  	INTEGER start
  	INTEGER vi
C	print *, 'Alex3041-here=',VhcAtt_Array(it)%PSize 
c	! Clean the remaining elements     
   	do vi = start,VhcAtt_Array(it)%PSize
c	if (it.eq.42) then
c	print *,'Alex200-here-0'
c	endif
     	VhcAtt_Array(it)%P(vi)%PathNode = 0 
     	VhcAtt_Array(it)%P(vi)%PathStop = 0 
     	VhcAtt_Array(it)%P(vi)%PathTime = 0 
     	VhcAtt_Array(it)%P(vi)%PathTimeDiff = 0 
   	enddo
C	print *, 'Alex3042-here=',VhcAtt_Array(it)%PSize
	END SUBROUTINE 

c	! -----------------------------------2DRemove
	SUBROUTINE VhcAtt_2DRemove()

  	INTEGER::vi
c	! Remove every element
  	do vi=1,VhcAtt_ArraySize
    	call VhcAtt_Remove(vi) 
  	enddo

c	! Remove entire array
  	if(ALLOCATED(VhcAtt_Array))then
    	DEALLOCATE(VhcAtt_Array,stat=vectorerror)
	if(vectorerror.ne.0)then
 	  write(911,*) "VhcAtt Destory"
 	  pause
	endif
  	endif
  	VhcAtt_ArraySize = 0

	END SUBROUTINE 

c	! *** End of VhcAtt_Array implementation ***

c	! --  Starting BusAtt_Array Implementation for Buses
c	! --  The implementation is similar to generic vehicles except the attribute defintiion 
c	! --  for buses are different from generic vehicles


	SUBROUTINE BusATT_Setup(it,NewSize)

  	INTEGER it, NewSize
  	TYPE(BusAttribute), POINTER :: tempP(:)
  	INTEGER :: vi
  	INTEGER :: OldSize

  	OldSize = 0
	
c	! create temp pointer to store contents of array
   	if ( BusAtt_Array(it)%PSize > 0 ) then
    	OldSize = BusAtt_Array(it)%PSize
    	ALLOCATE(tempP(BusAtt_Array(it)%PSize),stat=vectorerror)
	if(vectorerror.ne.0) then
  	  write(911,*)"allocate tmpP vectorerror"
   	  pause
   	endif

c	! Copy content of old array to temp pointer
    	do vi = 1, BusAtt_Array(it)%PSize
	   tempP(vi)%PathNode = BusAtt_Array(it)%P(vi)%PathNode 
	   tempP(vi)%StopMode = BusAtt_Array(it)%P(vi)%StopMode 
    	enddo
  
c	! Delete the old array
    	if (associated(BusAtt_Array(it)%P)) then
	  DEALLOCATE(BusAtt_Array(it)%P,stat=vectorerror)
	  if(vectorerror.ne.0) then
	    write(911,*) "deallocate BusAtt_1DArray vector error"
	    pause
        stop
	  endif
    	endif

	endif

c	! reallocate array
    	ALLOCATE(BusAtt_Array(it)%P(NewSize),stat=vectorerror)
	if(vectorerror.ne.0) then
	  write(911,*) "allocate BusAtt_1DArray vector error"
	  pause
      	stop
	endif
 
c	! Copy contents from temp back to array 
    	do vi = 1, OldSize
      	BusAtt_Array(it)%P(vi)%PathNode = tempP(vi)%PathNode
      	BusAtt_Array(it)%P(vi)%StopMode = tempP(vi)%StopMode
    	enddo

c	! initialize array for the remaining elements
    	do vi = OldSize+1,NewSize
	  BusAtt_Array(it)%P(vi)%PathNode = 0
	  BusAtt_Array(it)%P(vi)%StopMode = 0
	enddo

	BusAtt_Array(it)%PSize = NewSize

   	if(associated(tempP)) DEALLOCATE(tempP)

	END SUBROUTINE 

c	! Initialize the initial path array for buses
	SUBROUTINE BusAtt_2DSetup(SSize)
 
  	INTEGER SSize
  	INTEGER :: vi
c	! Remove existing array
  	if (ALLOCATED(BusAtt_Array)) then
    	call BusAtt_2DRemove()
  	endif

c	! Initialize increase size.
c	! Setup new array
  	if (.NOT. ALLOCATED(BusAtt_Array)) then
    	ALLOCATE(BusAtt_Array(SSize),stat=vectorerror)
	if(vectorerror.ne.0) then
 	  write(911,*) "BusAtt Setup"
      	pause
	endif
  	endif
  
c	! Initialize new size for each element
  	do vi = 1, SSize
   	BusAtt_Array(vi)%PSize = 0
  	enddo

	BusAtt_ArraySIZE = SSize
	

	END SUBROUTINE 


c	! This subroutine inserts a new element into the array
	SUBROUTINE BusAtt_Insert(it, Index1D, AttNo, Value)
 
  	INTEGER it, Index1D, AttNo, NewSize
  	INTEGER    Value
  	if (Index1D > BusAtt_Array(it)%PSize) then
	 NewSize = Index1D + m_IncreaseSize 
     	call BusAtt_Setup(it,NewSize )
  	endif
 
  	if (AttNo.eq.1) then
    	BusAtt_Array(it)%P(Index1D)%PathNode = Value
  	elseif (AttNo.eq.2) then
    	BusAtt_Array(it)%P(Index1D)%StopMode = Value
  	else
    	write(911,*) 'BusAtt_Insert error'
    	stop
  	endif
	
	END SUBROUTINE 


	INTEGER FUNCTION BusAtt_Value(it,Index1D,AttNo)
 
  	INTEGER it, Index1D, AttNo
  	INTEGER Value
  	if (Index1D > BusAtt_Array(it)%PSize) then
     	write(911,*)"BusAtt GetValue vector error"
     	stop
  	endif

  	if (AttNo.eq.1) then
     	BusAtt_Value = BusAtt_Array(it)%P(Index1D)%PathNode
  	elseif (AttNo.eq.2) then
     	BusAtt_Value = BusAtt_Array(it)%P(Index1D)%StopMode
  	else
    	write(911,*) 'get BusAtt_value error'
    	stop
  	endif  


	END FUNCTION 

	INTEGER FUNCTION buspath(it,Index1D)
	buspath = BusAtt_Array(it)%P(Index1D)%PathNode
	END FUNCTION

	INTEGER FUNCTION busstop(it,Index1D)
        busstop = BusAtt_Array(it)%P(Index1D)%StopMode        
	END FUNCTION


	INTEGER FUNCTION BusAtt_Size(it)
    	i = BusAtt_array(it)%PSize
    	do while (BusAtt_array(it)%p(i)%PathNode.lt.1) 
       	i = i - 1
    	enddo
	    
	BusAtt_Size = i
	END FUNCTION 

c	! -----------------------------------Remove
	SUBROUTINE BusAtt_Remove(it)
 
  	INTEGER it
  	if (BusAtt_Array(it)%PSize > 0) then
	DEALLOCATE(BusAtt_Array(it)%P,stat=vectorerror)
	if(vectorerror.ne.0) then
	  write(911,*)"deallocate BusAtt_Array vectorerror"
	  write(911,*)it
	  pause
	endif
	   BusAtt_Array(it)%PSize = 0 
   	endif

	END SUBROUTINE 

c	! -----------------------------------Clear
	SUBROUTINE BusAtt_Clear(it,start)
 
  	INTEGER it
  	INTEGER start
  	INTEGER vi
	 
c	! Clean the remaining elements     
   	do vi = start, BusAtt_Array(it)%PSize
     	BusAtt_Array(it)%P(vi)%PathNode = 0 
     	BusAtt_Array(it)%P(vi)%StopMode = 0 
   	enddo

	END SUBROUTINE 

c	! -----------------------------------2DRemove
	SUBROUTINE BusAtt_2DRemove()
 
  	INTEGER :: vi
c	! Remove every element
  	do vi = 1, BusAtt_ArraySize
    	call BusAtt_Remove(vi) 
  	enddo

c	! Remove entire array
  	if (ALLOCATED(BusAtt_Array)) then
    	DEALLOCATE(BusAtt_Array,stat=vectorerror)
	if(vectorerror.ne.0) then
 	  write(911,*)"BusAtt Destory"
 	  pause
	endif
  	endif
  	BusAtt_ArraySize = 0
	
	END SUBROUTINE 

	END MODULE 
